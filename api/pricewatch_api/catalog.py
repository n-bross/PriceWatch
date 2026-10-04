"""Product identity catalog, separate from dated retailer price observations."""

import csv
import fcntl
import gzip
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator
from sqlalchemy import Column, DateTime, Index, String, Table, Text, case, delete, func, select
from sqlalchemy.exc import SQLAlchemyError

from .barcodes import barcode_scope, valid_ean
from .database import Database, metadata, normalize
from .models import Retailer
from .models import Text as ShortText
from .sources import SourceError

OFF_EXPORT = "https://static.openfoodfacts.org/data/en.openfoodfacts.org.products.csv.gz"
ATTRIBUTION = {
    "name": "Open Food Facts",
    "url": "https://world.openfoodfacts.org/",
    "license": "ODbL-1.0",
    "license_url": "https://opendatacommons.org/licenses/odbl/1-0/",
}
SOURCE_PRIORITY = {
    "open_prices": 2,
    "german_supermarket_prices": 0,
    "rewe_price_data": 1,
    "open_food_facts": 10,
    "retailer_observation": 20,
    "verified_import": 30,
}
DATASET_ATTRIBUTION = {
    "name": "german-supermarket-prices / loukesio; includes Open Food Facts contributors",
    "url": "https://github.com/loukesio/german-supermarket-prices",
    "license": "ODbL-1.0",
    "license_url": ATTRIBUTION["license_url"],
}
products = Table(
    "product_catalog",
    metadata,
    Column("ean", String, primary_key=True),
    Column("name", String, nullable=False),
    Column("normalized_name", String, nullable=False),
    Column("brand", String),
    Column("package_label", String),
    Column("countries_json", Text, nullable=False),
    Column("reported_stores", Text),
    Column("categories_json", Text, nullable=False, server_default="[]"),
    Column("source", String, nullable=False),
    Column("source_url", String, nullable=False),
    Column("source_updated_at", DateTime(timezone=True)),
    Column("imported_at", DateTime(timezone=True), nullable=False),
)
Index("product_catalog_name", products.c.normalized_name)
articles = Table(
    "product_retailer_articles",
    metadata,
    Column("retailer", String, primary_key=True),
    Column("source_product_id", String, primary_key=True),
    # Empty store_id means a confirmed chain-wide article identity, not availability.
    Column("store_id", String, primary_key=True, server_default=""),
    Column("ean", String, nullable=False),
    Column("source_url", String, nullable=False),
    Column("note", String),
    Column("observed_at", DateTime(timezone=True), nullable=False),
)
Index("product_retailer_articles_ean", articles.c.ean)
product_sources = Table(
    "product_catalog_sources",
    metadata,
    Column("ean", String, primary_key=True),
    Column("source", String, primary_key=True),
    Column("payload_json", Text, nullable=False),
    Column("source_url", String, nullable=False),
    Column("source_updated_at", DateTime(timezone=True)),
    Column("imported_at", DateTime(timezone=True), nullable=False),
)


class ProductInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    ean: str
    name: ShortText
    brand: ShortText | None = None
    package_label: ShortText | None = None
    countries: list[Annotated[str, Field(min_length=1, max_length=80)]] = Field(max_length=100)
    reported_stores: str | None = Field(default=None, max_length=2000)
    categories: list[Annotated[str, Field(min_length=1, max_length=300)]] = Field(
        default_factory=list, max_length=100
    )
    source_url: HttpUrl
    source_updated_at: datetime | None = None

    @field_validator("ean")
    @classmethod
    def barcode(cls, value):
        if not valid_ean(value):
            raise ValueError("Provide a valid EAN-8, EAN-13 or GTIN-14")
        return value

    @field_validator("source_updated_at")
    @classmethod
    def aware_time(cls, value):
        if value is not None and value.utcoffset() is None:
            raise ValueError("source_updated_at needs a timezone")
        return value


class ProductBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    products: list[ProductInput] = Field(min_length=1, max_length=1000)


class ArticleIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    retailer: Retailer
    source_product_id: ShortText
    store_id: ShortText | None = None
    ean: str
    source_url: HttpUrl
    note: ShortText | None = None
    identity_confirmed: Literal[True]
    observed_at: datetime

    _barcode = field_validator("ean")(ProductInput.barcode.__func__)

    @field_validator("observed_at")
    @classmethod
    def valid_time(cls, value):
        if value.utcoffset() is None or value > datetime.now(UTC):
            raise ValueError("observed_at needs a timezone and cannot be in the future")
        return value


def off_product(row: dict) -> ProductInput | None:
    """Country tags are catalog metadata, not a claim of present store availability."""
    countries = [v.strip() for v in row.get("countries_tags", "").split(",") if v.strip()]
    if "en:germany" not in countries:
        return None
    code = row.get("code", "")
    if not valid_ean(code):
        return None
    name = (row.get("product_name") or row.get("generic_name") or "").strip()
    if not name:
        return None
    timestamp = row.get("last_modified_t", "")
    updated = datetime.fromtimestamp(int(timestamp), UTC) if timestamp.isdigit() else None
    return ProductInput(
        ean=code,
        name=name[:300],
        brand=(row.get("brands") or "")[:300] or None,
        package_label=(row.get("quantity") or "")[:300] or None,
        countries=countries[:100],
        reported_stores=(row.get("stores") or "")[:2000] or None,
        source_url=f"https://world.openfoodfacts.org/product/{code}",
        source_updated_at=updated,
        categories=[v.strip() for v in (row.get("categories_tags") or "").split(",") if v.strip()][
            :100
        ],
    )


class ProductRepository:
    def __init__(self, db: Database):
        self.db = db

    def upsert(self, items: list[ProductInput], source="verified_import"):
        now = datetime.now(UTC)
        rows = []
        for item in items:
            data = item.model_dump(exclude={"countries", "categories"})
            data.update(
                countries_json=json.dumps(item.countries),
                source=source,
                imported_at=now,
                normalized_name=normalize(item.name),
                source_url=str(item.source_url),
                categories_json=json.dumps(item.categories),
            )
            rows.append(data)
        if not rows:
            return 0
        insert = self.db._insert(products)
        # Trusted operator corrections survive the next community-data refresh.
        priority = case(SOURCE_PRIORITY, value=products.c.source, else_=-1)
        where = priority <= SOURCE_PRIORITY.get(source, -1)
        stmt = insert.on_conflict_do_update(
            index_elements=["ean"],
            set_={c.name: insert.excluded[c.name] for c in products.c if c.name != "ean"},
            where=where,
        )
        with self.db.engine.begin() as conn:
            facts = self.db._insert(product_sources)
            source_rows = []
            for item in items:
                payload = item.model_dump(mode="json")
                source_rows.append(
                    dict(
                        ean=item.ean,
                        source=source,
                        payload_json=json.dumps(payload),
                        source_url=str(item.source_url),
                        source_updated_at=item.source_updated_at,
                        imported_at=now,
                    )
                )
            conn.execute(
                facts.on_conflict_do_update(
                    index_elements=["ean", "source"],
                    set_={
                        k: facts.excluded[k]
                        for k in ("payload_json", "source_url", "source_updated_at", "imported_at")
                    },
                ),
                source_rows,
            )
            result = conn.execute(stmt, rows)
            return result.rowcount

    @staticmethod
    def serialize(row):
        data = dict(row)
        data.pop("normalized_name")
        data["countries"] = json.loads(data.pop("countries_json"))
        data["categories"] = json.loads(data.pop("categories_json"))
        data["availability"] = "not_verified"
        data["barcode_scope"] = barcode_scope(data["ean"])
        data["attribution"] = {
            "open_food_facts": ATTRIBUTION,
            "german_supermarket_prices": DATASET_ATTRIBUTION,
        }.get(data["source"])
        for key in ("source_updated_at", "imported_at"):
            if data[key] and data[key].tzinfo is None:
                data[key] = data[key].replace(tzinfo=UTC)
        return data

    def query(self, q=None, ean=None, limit=50, offset=0, category=None, brand=None):
        filters = []
        if ean:
            filters.append(products.c.ean == ean)
        if q:
            term = normalize(q)
            filters.append(products.c.normalized_name.contains(term, autoescape=True))
        if category:
            filters.append(
                products.c.categories_json.contains(json.dumps(category), autoescape=True)
            )
        if brand:
            filters.append(func.lower(products.c.brand).contains(brand.casefold(), autoescape=True))
        with self.db.engine.connect() as conn:
            total = conn.scalar(select(func.count()).select_from(products).where(*filters))
            rows = (
                conn.execute(
                    select(products)
                    .where(*filters)
                    .order_by(products.c.normalized_name, products.c.ean)
                    .limit(limit)
                    .offset(offset)
                )
                .mappings()
                .all()
            )
        return {
            "items": [self.serialize(r) for r in rows],
            "total": total,
            "limit": limit,
            "offset": offset,
            "coverage": "Known products; not a complete current assortment",
        }

    def detail(self, ean):
        with self.db.engine.connect() as conn:
            row = conn.execute(select(products).where(products.c.ean == ean)).mappings().first()
            if row is None:
                return None
            links = conn.execute(select(articles).where(articles.c.ean == ean)).mappings().all()
            records = conn.execute(select(product_sources).where(product_sources.c.ean == ean))
            records = records.mappings().all()
        data = self.serialize(row)
        data["retailer_articles"] = [dict(r) for r in links]
        data["source_records"] = [
            {**dict(r), "product": json.loads(r["payload_json"])} for r in records
        ]
        for record in data["source_records"]:
            record.pop("payload_json")
        # Initial imports before source-record tracking still retain their provenance.
        if not any(r["source"] == data["source"] for r in data["source_records"]):
            data["source_records"].append(
                {
                    "source": data["source"],
                    "source_url": data["source_url"],
                    "source_updated_at": data["source_updated_at"],
                    "imported_at": data["imported_at"],
                    "product": {
                        k: data[k]
                        for k in (
                            "ean",
                            "name",
                            "brand",
                            "package_label",
                            "countries",
                            "categories",
                        )
                    },
                }
            )
        return data

    def link(self, item: ArticleIdentity):
        if self.detail(item.ean) is None:
            raise ValueError("Unknown barcode: import the product first")
        data = item.model_dump(exclude={"identity_confirmed"})
        data["store_id"] = item.store_id or ""
        data["source_url"] = str(item.source_url)
        insert = self.db._insert(articles).values(**data)
        with self.db.engine.begin() as conn:
            conn.execute(
                insert.on_conflict_do_update(
                    index_elements=["retailer", "source_product_id", "store_id"],
                    set_=data,
                    where=insert.excluded.observed_at >= articles.c.observed_at,
                )
            )

    def unlink(self, retailer, source_product_id, store_id=None):
        with self.db.engine.begin() as conn:
            return conn.execute(
                delete(articles).where(
                    articles.c.retailer == retailer,
                    articles.c.source_product_id == source_product_id,
                    articles.c.store_id == (store_id or ""),
                )
            ).rowcount

    def status(self):
        with self.db.engine.connect() as conn:
            count = conn.scalar(select(func.count()).select_from(products))
            linked = conn.scalar(select(func.count()).select_from(articles))
        return {
            "product_count": count,
            "confirmed_article_links": linked,
            "import": self.db.source_runs().get("product_catalog_off"),
            "attribution": ATTRIBUTION,
            "coverage": "Germany-tagged community catalog, not all supermarket products; "
            "reported_stores is unverified source metadata; no inferred prices",
        }

    def import_off_csv(self, path: Path):
        csv.field_size_limit(20_000_000)
        seen = german = rejected = processed = 0
        batch = []
        opener = gzip.open if path.suffix == ".gz" else open
        with opener(path, "rt", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            if not {"code", "product_name", "countries_tags"} <= set(reader.fieldnames or []):
                raise SourceError("Open Food Facts export has an unexpected header")
            for row in reader:
                seen += 1
                if "en:germany" not in row.get("countries_tags", "").split(","):
                    continue
                german += 1
                try:
                    item = off_product(row)
                except (ValueError, OverflowError, OSError):
                    item = None
                if item is None:
                    rejected += 1
                    continue
                batch.append(item)
                if len(batch) == 500:
                    processed += self.upsert(batch, "open_food_facts")
                    batch = []
            processed += self.upsert(batch, "open_food_facts")
        return {
            "scanned": seen,
            "germany_tagged": german,
            "rejected": rejected,
            "processed": processed,
        }

    def import_dataset_products(self, path: Path):
        """Import identities from the user's CSV dataset, never promote its old prices."""
        grouped = {}
        rejected = 0
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if not {"ean_barcode", "product_name", "retailer", "collected_at"} <= set(
                reader.fieldnames or []
            ):
                raise SourceError("Expected german-supermarket-prices CSV columns")
            for row in reader:
                ean = row["ean_barcode"]
                if not valid_ean(ean) or not row["product_name"].strip():
                    rejected += 1
                    continue
                if ean not in grouped:
                    stamp = row.get("collected_at")
                    updated = datetime.fromisoformat(stamp).replace(tzinfo=UTC) if stamp else None
                    category = (row.get("category") or "").removeprefix("Angebot · ").strip()
                    grouped[ean] = ProductInput(
                        ean=ean,
                        name=row["product_name"][:300],
                        countries=["en:germany"],
                        categories=[category[:300]] if category else [],
                        source_url="https://github.com/loukesio/german-supermarket-prices/blob/main/data/prices.csv",
                        source_updated_at=updated,
                    )
                item = grouped[ean]
                stores = set((item.reported_stores or "").split(", ")) - {""}
                stores.add(row["retailer"])
                item.reported_stores = ", ".join(sorted(stores))[:2000]
        items = list(grouped.values())
        processed = 0
        for offset in range(0, len(items), 500):
            processed += self.upsert(items[offset : offset + 500], "german_supermarket_prices")
        return {
            "unique_barcodes": len(items),
            "canonical_updates": processed,
            "rejected_rows": rejected,
            "prices_imported": 0,
        }

    def sync_off(self, directory: Path):
        """Weekly bulk import, bounded download, conditional requests, one worker at a time."""
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / "sync.lock").open("w") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise SourceError("Product catalog import is already running") from None
            self.db.record_run(
                "product_catalog_off", "running", 0, "Downloading/checking bulk export"
            )
            path = directory / "openfoodfacts.csv.gz"
            state_path = directory / "download.json"
            headers = {"User-Agent": "PriceWatch/0.1 (https://vps.tail179a46.ts.net:9450/docs)"}
            try:
                state = json.loads(state_path.read_text()) if state_path.exists() else {}
                if path.exists() and state.get("etag"):
                    headers["If-None-Match"] = state["etag"]
                with httpx.Client(timeout=60, follow_redirects=True) as client:
                    with client.stream("GET", OFF_EXPORT, headers=headers) as response:
                        if response.status_code == 304 and state.get("imported"):
                            self.db.record_run(
                                "product_catalog_off",
                                "ok",
                                state["processed"],
                                "Bulk export unchanged",
                            )
                            return {"status": "unchanged", **state}
                        if response.status_code != 304:
                            response.raise_for_status()
                            state = {
                                "etag": response.headers.get("etag"),
                                "last_modified": response.headers.get("last-modified"),
                                "imported": False,
                            }
                            part = directory / "openfoodfacts.csv.gz.part"
                            size = 0
                            with part.open("wb") as output:
                                for chunk in response.iter_bytes(1024 * 1024):
                                    size += len(chunk)
                                    if size > 4 * 1024**3:
                                        raise SourceError(
                                            "Export exceeds 4 GiB compressed download limit"
                                        )
                                    output.write(chunk)
                            part.replace(path)
                            state_path.write_text(json.dumps(state))
                self.db.record_run(
                    "product_catalog_off", "running", 0, "Importing Germany-tagged products"
                )
                result = self.import_off_csv(path)
                state.update(imported=True, **result)
                state_path.write_text(json.dumps(state))
                self.db.record_run(
                    "product_catalog_off", "ok", result["processed"], json.dumps(result)
                )
                return result
            except (
                httpx.HTTPError,
                OSError,
                EOFError,
                csv.Error,
                ValueError,
                SQLAlchemyError,
                SourceError,
            ) as exc:
                self.db.record_run("product_catalog_off", "error", 0, str(exc)[:1000])
                raise SourceError(f"Product catalog import failed: {exc}") from exc
