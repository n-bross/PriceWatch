"""Private receipt OCR and conservative, reviewable catalog checks."""

import hashlib
import json
import os
import re
import subprocess
from datetime import UTC, date, datetime
from decimal import Decimal
from difflib import SequenceMatcher
from pathlib import Path
from uuid import uuid4

import pymupdf
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import Boolean, Column, DateTime, String, Table, Text, delete, select, update

from .database import Database, metadata, normalize, prices
from .models import Retailer, Zip
from .sources import SourceError

MAX_RECEIPT_BYTES = 20 * 1024 * 1024
receipts = Table(
    "price_receipts",
    metadata,
    Column("id", String, primary_key=True),
    Column("content_hash", String, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    Column("metadata_json", Text, nullable=False),
    Column("text", Text, nullable=False),
    Column("lines_json", Text, nullable=False),
    Column("comparisons_json", Text, nullable=False),
    Column("confirmed", Boolean, nullable=False),
    Column("extraction_method", String, nullable=False),
)


class ReceiptDiscount(BaseModel):
    original_total_cents: int = Field(gt=0, le=100_000_000, strict=True)
    percent: Decimal | None = Field(default=None, gt=0, le=100, decimal_places=2)
    kind: str = Field(default="other", pattern="^(sticker|coupon|article_promotion|other)$")
    note: str | None = Field(default=None, max_length=300)


class ReceiptLine(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    paid_total_cents: int = Field(ge=0, le=100_000_000, strict=True)
    quantity: Decimal = Field(default=Decimal(1), gt=0, le=10000, decimal_places=3)
    quantity_unit: str = Field(default="item", pattern="^(item|kg|l)$")
    catalog_price_id: str | None = None
    # A reviewer must confirm identical package/variant, not just similar names.
    identity_confirmed: bool = False
    membership_used: bool = False
    raw_line: str | None = Field(default=None, max_length=1000)
    needs_quantity_review: bool = False
    discount: ReceiptDiscount | None = None

    @model_validator(mode="after")
    def consistent_discount(self):
        if self.discount:
            original = self.discount.original_total_cents
            if self.paid_total_cents >= original:
                raise ValueError("Discount requires paid total below original total")
            if self.discount.percent is not None:
                net = Decimal(original) * (1 - self.discount.percent / 100)
                expected = int(net.quantize(Decimal(1), rounding="ROUND_HALF_UP"))
                if abs(expected - self.paid_total_cents) > 1:
                    raise ValueError("Discount percentage does not match original and paid totals")
        return self


class ReceiptReview(BaseModel):
    retailer: Retailer | None = None
    purchase_date: date | None = None
    postal_code: Zip | None = None
    store_id: str | None = Field(default=None, min_length=1, max_length=300)
    lines: list[ReceiptLine] = Field(max_length=300)
    confirmed: bool = False

    @model_validator(mode="after")
    def valid_purchase(self):
        if self.purchase_date and self.purchase_date > date.today():
            raise ValueError("Purchase date cannot be in the future")
        if self.confirmed and (not self.retailer or not self.purchase_date):
            raise ValueError("Confirm retailer and purchase date before reviewing")
        return self


def extract_receipt(content: bytes):
    if not content or len(content) > MAX_RECEIPT_BYTES:
        raise SourceError("Receipt must be between 1 byte and 20 MiB")
    supported = content.startswith((b"%PDF-", b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff"))
    if not supported:
        raise SourceError("Use a PDF, PNG or JPEG receipt")
    texts, methods = [], []
    try:
        with pymupdf.open(stream=content) as document:
            if document.needs_pass or not 1 <= len(document) <= 8:
                raise SourceError("Receipt is encrypted or exceeds eight pages")
            for page in document:
                text = page.get_text("text", sort=True)
                method = "pdf_text"
                if len(text.strip()) < 40:
                    # Bound raster memory before rendering untrusted documents.
                    scale = min(
                        3 if document.is_pdf else 1,
                        (15_000_000 / max(1, page.rect.width * page.rect.height)) ** 0.5,
                    )
                    if scale < 0.1:
                        raise SourceError("Receipt page dimensions exceed limits")
                    raster = page.get_pixmap(
                        matrix=pymupdf.Matrix(scale, scale), colorspace=pymupdf.csRGB, alpha=False
                    )
                    process = subprocess.run(
                        ["tesseract", "stdin", "stdout", "-l", "deu+eng", "--psm", "6"],
                        input=raster.tobytes("png"),
                        capture_output=True,
                        timeout=45,
                        check=True,
                        env={**os.environ, "OMP_THREAD_LIMIT": "1"},
                    )
                    text, method = process.stdout.decode(), "tesseract_ocr"
                if len(text) > 100_000:
                    raise SourceError("Receipt text exceeds extraction limits")
                texts.append(text)
                methods.append(method)
    except SourceError:
        raise
    except Exception as exc:
        raise SourceError(
            "Receipt extraction failed; check file and local Tesseract installation"
        ) from exc
    text = "\n".join(texts)
    if not text.strip():
        raise SourceError("No readable receipt text found")
    return text, "+".join(sorted(set(methods)))


def parse_receipt(text: str):
    """Propose lines, never silently treat totals, coupons or deposits as products."""
    lines, excluded = [], []
    ignore = re.compile(
        r"^(summe|gesamt|total|zu zahlen|bar(?:zahlung)?|karte|ec[- ]|visa|mastercard|"
        r"r[üu]ckgeld|gegeben|mwst|ust|steuer|rabatt|coupon|bonus|pfand|leergut|"
        r"gutschein|zahlung|betrag|saldo)\b",
        re.I,
    )
    for raw in text.splitlines():
        raw = raw.strip()
        if re.match(r"^\d+[,.]?\d*\s*[xX*]\s+\d+[,.]\d{2}", raw):
            excluded.append(raw)
            if lines:
                lines[-1].needs_quantity_review = True
            continue
        match = re.fullmatch(r"(.+?)\s+(-?\d{1,6}[,.]\d{2})\s*(?:EUR|€)?\s*[A-D]?", raw, re.I)
        if not match:
            continue
        name, amount = match.groups()
        if ignore.search(name) or amount.startswith("-") or not re.search(r"[a-zäöü]", name, re.I):
            excluded.append(raw)
            continue
        if len(name) > 300:
            excluded.append(raw)
            continue
        # Quantities printed on a separate line cannot be resolved reliably by OCR.
        suspect_quantity = bool(re.search(r"\b\d+[,.]?\d*\s*(?:x|kg|l)\b", name, re.I))
        lines.append(
            ReceiptLine(
                name=name,
                paid_total_cents=int(Decimal(amount.replace(",", ".")) * 100),
                raw_line=raw,
                needs_quantity_review=suspect_quantity,
            )
        )
        if len(lines) > 300:
            raise SourceError("Receipt exceeds 300 proposed product lines")
    retailer = None
    header = normalize(" ".join(text.splitlines()[:12]))
    for label, code in [
        ("aldi sud", "aldi_sued"),
        ("aldi nord", "aldi_nord"),
        ("penny", "penny"),
        ("rewe", "rewe"),
        ("kaufland", "kaufland"),
        ("lidl", "lidl"),
        ("edeka", "edeka"),
    ]:
        if re.search(r"\b" + label + r"\b", header):
            if retailer and retailer != code:
                retailer = None
                break
            retailer = code
    purchase_date = None
    for match in re.finditer(r"\b(\d{2})[./](\d{2})[./](\d{4}|\d{2})\b", text):
        day, month, year = map(int, match.groups())
        try:
            candidate = date(year + 2000 if year < 100 else year, month, day)
            if candidate <= date.today():
                purchase_date = candidate
                break
        except ValueError:
            continue
    return ReceiptReview(retailer=retailer, purchase_date=purchase_date, lines=lines), excluded


def matching_key(text):
    return re.sub(r"[^a-z0-9]+", " ", normalize(text)).strip()


class ReceiptRepository:
    def __init__(self, db: Database, data_dir: str):
        self.db = db
        self.data_dir = Path(data_dir)

    def compare(self, review: ReceiptReview):
        if not review.retailer or not review.purchase_date:
            return [
                {
                    "line": i,
                    "status": "missing_metadata",
                    "note": "Retailer and purchase date required",
                    "candidates": [],
                }
                for i, _ in enumerate(review.lines)
            ]
        filters = [
            prices.c.retailer == review.retailer,
            prices.c.valid_from <= review.purchase_date,
            prices.c.valid_until >= review.purchase_date,
        ]
        # No neighboring stores: a receipt pertains to its actual store only.
        with self.db.engine.connect() as conn:
            catalog = [dict(r) for r in conn.execute(select(prices).where(*filters)).mappings()]
        results = []
        for i, line in enumerate(review.lines):
            candidates = []
            for row in catalog:
                if row["scope"] == "store" and row["store_id"] != review.store_id:
                    continue
                if row["scope"] == "postal_code" and row["postal_code"] != review.postal_code:
                    continue
                if row["requires_membership"] != line.membership_used:
                    continue
                names = [
                    matching_key(row["name"]),
                    matching_key(" ".join(filter(None, [row["brand"], row["name"]]))),
                ]
                exact = matching_key(line.name) in names
                score = max(
                    SequenceMatcher(None, matching_key(line.name), name).ratio() for name in names
                )
                if row["id"] == line.catalog_price_id or exact or score >= 0.45:
                    candidates.append(
                        {
                            "id": row["id"],
                            "name": row["name"],
                            "brand": row["brand"],
                            "price_cents": row["price_cents"],
                            "package_label": row["package_label"],
                            "unit_price_cents": str(row["unit_price_cents"])
                            if row["unit_price_cents"] is not None
                            else None,
                            "unit_price_unit": row["unit_price_unit"],
                            "scope": row["scope"],
                            "store_id": row["store_id"],
                            "source_url": row["source_url"],
                            "observed_at": row["observed_at"].isoformat(),
                            "valid_from": str(row["valid_from"]),
                            "valid_until": str(row["valid_until"]),
                            "is_listed": row["is_listed"],
                            "requires_membership": row["requires_membership"],
                            "conditions": row["conditions"],
                            "exact_name": exact,
                            "similarity": round(score, 3),
                        }
                    )
            candidates.sort(
                key=lambda c: (c["id"] == line.catalog_price_id, c["exact_name"], c["similarity"]),
                reverse=True,
            )
            candidates = candidates[:5]
            selected = next((c for c in candidates if c["id"] == line.catalog_price_id), None)
            exact = [c for c in candidates if c["exact_name"]]
            provisional = not line.catalog_price_id and len(exact) == 1
            if provisional:
                selected = exact[0]
            result = {
                "line": i,
                "status": "needs_review",
                "candidates": candidates,
                "selected_id": None,
            }
            if line.catalog_price_id and not selected:
                result.update(
                    status="invalid_selection",
                    note="Selected price does not match store, date or membership",
                )
            elif not candidates:
                result.update(
                    status="not_found",
                    note="No suitable stored price; not proof of a wrong receipt",
                )
            elif (
                selected
                and (provisional or (review.confirmed and line.identity_confirmed))
                and not line.needs_quantity_review
            ):
                # Explicit human confirmation covers identical product, pack size and variant.
                if line.quantity_unit in ["kg", "l"]:
                    if (
                        selected["unit_price_unit"] != line.quantity_unit
                        or selected["unit_price_cents"] is None
                    ):
                        result.update(status="unit_unknown", note="No matching catalog base unit")
                        results.append(result)
                        continue
                    expected = Decimal(selected["unit_price_cents"]) * line.quantity
                else:
                    if "lose" in (selected["package_label"] or "").lower():
                        result.update(
                            status="unit_unknown", note="Loose produce requires kg/l quantity"
                        )
                        results.append(result)
                        continue
                    expected = Decimal(selected["price_cents"]) * line.quantity
                expected_cents = int(expected.quantize(Decimal(1), rounding="ROUND_HALF_UP"))
                comparison_total = (
                    line.discount.original_total_cents if line.discount else line.paid_total_cents
                )
                delta = comparison_total - expected_cents
                advertised = selected["scope"] != "store"
                status = (
                    ("advertised_match" if abs(delta) <= 1 else "advertised_difference")
                    if advertised
                    else ("match" if abs(delta) <= 1 else "mismatch")
                )
                result.update(
                    status=f"provisional_{status}" if provisional else status,
                    selected_id=selected["id"],
                    expected_total_cents=expected_cents,
                    paid_total_cents=line.paid_total_cents,
                    compared_total_cents=comparison_total,
                    discount_cents=(comparison_total - line.paid_total_cents),
                    difference_cents=delta,
                    review_required=provisional,
                    note="Chain advertisement; branch applicability unverified"
                    if advertised
                    else "Compared with this store's catalog entry",
                )
                if provisional:
                    result["note"] = (
                        "Automatic proposal only; confirm OCR, quantity and identical pack/variant"
                    )
            else:
                result["note"] = (
                    "Confirm receipt text, quantity, identical package/variant "
                    "and a catalog candidate"
                )
            results.append(result)
        return results

    def upload(self, content: bytes, supplied: dict):
        digest = hashlib.sha256(content).hexdigest()
        text, method = extract_receipt(content)
        proposal, excluded = parse_receipt(text)
        values = proposal.model_dump()
        values.update({k: v for k, v in supplied.items() if v is not None})
        review = ReceiptReview(**values)
        receipt_id = str(uuid4())
        now = datetime.now(UTC)
        comparison = self.compare(review)
        self.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = self.data_dir / receipt_id
        path.write_bytes(content)
        path.chmod(0o600)
        row = dict(
            id=receipt_id,
            content_hash=digest,
            created_at=now,
            updated_at=now,
            metadata_json=json.dumps(review.model_dump(mode="json", exclude={"lines"})),
            text=text,
            lines_json=json.dumps([p.model_dump(mode="json") for p in review.lines]),
            comparisons_json=json.dumps(comparison),
            confirmed=False,
            extraction_method=method,
        )
        with self.db.engine.begin() as conn:
            conn.execute(receipts.insert().values(**row))
        return {**self.get(receipt_id), "excluded_lines": excluded}

    def get(self, receipt_id: str):
        with self.db.engine.connect() as conn:
            row = (
                conn.execute(select(receipts).where(receipts.c.id == receipt_id)).mappings().first()
            )
        if not row:
            raise KeyError(receipt_id)
        return {
            "id": row["id"],
            "created_at": row["created_at"].isoformat(),
            "updated_at": row["updated_at"].isoformat(),
            "metadata": json.loads(row["metadata_json"]),
            "text": row["text"],
            "lines": json.loads(row["lines_json"]),
            "comparisons": json.loads(row["comparisons_json"]),
            "confirmed": row["confirmed"],
            "extraction_method": row["extraction_method"],
            "note": "OCR and candidate matches require review. "
            "Receipt prices never overwrite retailer offers.",
        }

    def review(self, receipt_id: str, review: ReceiptReview, *, queue: bool = True):
        self.get(receipt_id)
        comparisons = self.compare(review)
        with self.db.engine.begin() as conn:
            conn.execute(
                update(receipts)
                .where(receipts.c.id == receipt_id)
                .values(
                    updated_at=datetime.now(UTC),
                    confirmed=review.confirmed,
                    metadata_json=json.dumps(review.model_dump(mode="json", exclude={"lines"})),
                    lines_json=json.dumps([p.model_dump(mode="json") for p in review.lines]),
                    comparisons_json=json.dumps(comparisons),
                )
            )
        if (
            queue
            and review.confirmed
            and any(
                c["status"] in ["mismatch", "advertised_difference", "not_found"]
                for c in comparisons
            )
        ):
            from .tracker import queue_recheck

            queue_recheck(self.db, receipt_id, review.retailer, review.postal_code)
        return self.get(receipt_id)

    def list(self, limit: int, offset: int):
        with self.db.engine.connect() as conn:
            rows = conn.execute(
                select(
                    receipts.c.id,
                    receipts.c.created_at,
                    receipts.c.metadata_json,
                    receipts.c.confirmed,
                )
                .order_by(receipts.c.created_at.desc())
                .limit(limit)
                .offset(offset)
            ).mappings()
            return [
                {
                    "id": r["id"],
                    "created_at": r["created_at"].isoformat(),
                    "metadata": json.loads(r["metadata_json"]),
                    "confirmed": r["confirmed"],
                }
                for r in rows
            ]

    def delete(self, receipt_id: str):
        self.get(receipt_id)
        with self.db.engine.begin() as conn:
            conn.execute(delete(receipts).where(receipts.c.id == receipt_id))
        (self.data_dir / receipt_id).unlink(missing_ok=True)
