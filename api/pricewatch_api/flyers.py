import hashlib
import json
import re
import subprocess
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Annotated, Literal

import pymupdf
from pydantic import BaseModel, Field, HttpUrl, model_validator
from sqlalchemy import (
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    and_,
    delete,
    func,
    or_,
    select,
)

from .database import Database, metadata, normalize
from .models import Retailer, Zip
from .sources import SourceError

MAX_PDF_BYTES = 80 * 1024 * 1024
MAX_PAGES = 120
flyers = Table(
    "price_flyers",
    metadata,
    Column("id", String, primary_key=True),
    Column("retailer", String, nullable=False),
    Column("title", String, nullable=False),
    Column("source_url", String, nullable=False),
    Column("valid_from", Date, nullable=False),
    Column("valid_until", Date, nullable=False),
    Column("scope", String, nullable=False),
    Column("postal_code", String),
    Column("store_id", String),
    Column("region_label", String),
    Column("observed_at", DateTime(timezone=True), nullable=False),
    Column("page_count", Integer, nullable=False),
    Column("needs_ocr_pages", Integer, nullable=False),
)
pages = Table(
    "price_flyer_pages",
    metadata,
    Column("flyer_id", String, ForeignKey("price_flyers.id", ondelete="CASCADE"), primary_key=True),
    Column("page", Integer, primary_key=True),
    Column("text", Text, nullable=False),
    Column("normalized_text", Text, nullable=False),
    Column("method", String, nullable=False),
)


class FlyerInfo(BaseModel):
    title: Annotated[str, Field(min_length=1, max_length=300)]
    retailer: Retailer
    source_url: HttpUrl
    valid_from: date
    valid_until: date
    scope: Literal["chain_advertised", "regional", "postal_code", "store"]
    postal_code: Zip | None = None
    store_id: str | None = None
    region_label: str | None = None

    @model_validator(mode="after")
    def consistent(self):
        if self.valid_until < self.valid_from:
            raise ValueError("Invalid flyer date interval")
        if self.scope == "postal_code" and not self.postal_code:
            raise ValueError("Postal code required")
        if self.scope == "store" and not self.store_id:
            raise ValueError("Store ID required")
        if self.scope == "regional" and not self.region_label:
            raise ValueError("Region label required; do not guess nationwide applicability")
        if self.scope in ["regional", "chain_advertised"] and (self.postal_code or self.store_id):
            raise ValueError("Do not assign regional/general flyers to an unverified store")
        return self


def extract_pdf(content: bytes, *, ocr: bool = False):
    if len(content) > MAX_PDF_BYTES or not content.startswith(b"%PDF-"):
        raise SourceError("Expected a PDF no larger than 80 MiB")
    result = []
    try:
        with pymupdf.open(stream=content, filetype="pdf") as document:
            if document.needs_pass or not 1 <= len(document) <= MAX_PAGES:
                raise SourceError("PDF is encrypted, empty, or exceeds 120 pages")
            for index, page in enumerate(document):
                text = page.get_text("text", sort=True)
                method = "pdf_text"
                if len(text.strip()) < 40:
                    method = "needs_ocr"
                    if ocr:
                        image = page.get_pixmap(dpi=150).tobytes("png")
                        process = subprocess.run(
                            ["tesseract", "stdin", "stdout", "-l", "deu+eng"],
                            input=image,
                            capture_output=True,
                            timeout=30,
                            check=True,
                        )
                        text, method = process.stdout.decode(), "ocr_unverified"
                if len(text) > 200_000:
                    raise SourceError("PDF page text exceeds extraction limit")
                result.append({"page": index + 1, "text": text, "method": method})
    except SourceError:
        raise
    except Exception as exc:
        raise SourceError("PDF text extraction failed") from exc
    return result


class FlyerRepository:
    def __init__(self, db: Database, data_dir: str):
        self.db = db
        self.data_dir = Path(data_dir)

    def pdf_path(self, flyer_id: str):
        return self.data_dir / f"{flyer_id}.pdf"

    def import_pdf(self, info: FlyerInfo, content: bytes, *, ocr: bool = False):
        extracted = extract_pdf(content, ocr=ocr)
        hash_input = json.dumps(info.model_dump(mode="json"), sort_keys=True).encode() + content
        flyer_id = hashlib.sha256(hash_input).hexdigest()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.pdf_path(flyer_id).write_bytes(content)
        values = {
            **info.model_dump(),
            "id": flyer_id,
            "source_url": str(info.source_url),
            "observed_at": datetime.now(UTC),
            "page_count": len(extracted),
            "needs_ocr_pages": sum(p["method"] == "needs_ocr" for p in extracted),
        }
        with self.db.engine.begin() as conn:
            previous_ids = list(
                conn.scalars(
                    select(flyers.c.id).where(
                        flyers.c.id != flyer_id,
                        *[
                            flyers.c[field] == values[field]
                            for field in (
                                "retailer",
                                "source_url",
                                "valid_from",
                                "valid_until",
                                "scope",
                                "postal_code",
                                "store_id",
                                "region_label",
                            )
                        ],
                    )
                )
            )
            if previous_ids:
                # Keep original PDF files archived, but search only the latest revision.
                conn.execute(delete(pages).where(pages.c.flyer_id.in_(previous_ids)))
                conn.execute(delete(flyers).where(flyers.c.id.in_(previous_ids)))
            stmt = self.db._insert(flyers).values(**values)
            conn.execute(stmt.on_conflict_do_update(index_elements=["id"], set_=values))
            for page in extracted:
                row = {**page, "flyer_id": flyer_id, "normalized_text": normalize(page["text"])}
                stmt = self.db._insert(pages).values(**row)
                conn.execute(
                    stmt.on_conflict_do_update(index_elements=["flyer_id", "page"], set_=row)
                )
        return {
            "id": flyer_id,
            "pages": len(extracted),
            "needs_ocr_pages": values["needs_ocr_pages"],
            "price_imported": False,
            "note": "Searchable source text; price/product assignments need verification",
        }

    def search(
        self,
        *,
        q: str | None,
        retailer: str | None,
        on: date,
        postal_code: str | None,
        limit: int,
        offset: int,
    ):
        filters = [flyers.c.valid_from <= on, flyers.c.valid_until >= on]
        if retailer:
            filters.append(flyers.c.retailer == retailer)
        if q:
            filters.append(pages.c.normalized_text.contains(normalize(q), autoescape=True))
        if postal_code:
            filters.append(
                or_(
                    flyers.c.scope == "chain_advertised",
                    and_(
                        flyers.c.postal_code == postal_code,
                        flyers.c.scope.in_(["postal_code", "store"]),
                    ),
                )
            )
        joined = flyers.join(pages)
        with self.db.engine.connect() as conn:
            total = conn.scalar(select(func.count()).select_from(joined).where(*filters))
            records = conn.execute(
                select(flyers, pages.c.page, pages.c.text, pages.c.method)
                .select_from(joined)
                .where(*filters)
                .order_by(flyers.c.id, pages.c.page)
                .limit(limit)
                .offset(offset)
            ).mappings()
            items = []
            for record in records:
                row = dict(record)
                text = row.pop("text")
                if q:
                    index = normalize(text).find(normalize(q))
                    excerpt = text[max(0, index - 180) : index + 700]
                else:
                    excerpt = text[:1000]
                row["excerpt"] = excerpt
                row["price_candidates"] = re.findall(r"\b\d{1,5}[.,]\d{2}\b", excerpt)[:30]
                row["extraction_status"] = "unverified_text"
                row["pdf_path"] = f"/v1/flyers/{row['id']}/pdf#page={row['page']}"
                items.append(row)
        return {
            "items": items,
            "total": total,
            "limit": limit,
            "offset": offset,
            "note": "Amounts may include dates, unit prices, deposits or app prices; "
            "these are not verified product prices",
        }

    def counts(self, on: date):
        with self.db.engine.connect() as conn:
            return {
                row["retailer"]: row["page_count"]
                for row in conn.execute(
                    select(
                        flyers.c.retailer,
                        func.sum(flyers.c.page_count).label("page_count"),
                    )
                    .where(flyers.c.valid_from <= on, flyers.c.valid_until >= on)
                    .group_by(flyers.c.retailer)
                ).mappings()
            }
