import hashlib
import json
import unicodedata
from datetime import UTC, date, datetime, timedelta
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    and_,
    create_engine,
    func,
    or_,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from .barcodes import barcode_scope
from .models import Price, PriceInput, PricePage

metadata = MetaData()
prices = Table(
    "price_catalog",
    metadata,
    Column("id", String, primary_key=True),
    Column("source", String, nullable=False),
    Column("retailer", String, nullable=False),
    Column("source_product_id", String, nullable=False),
    Column("name", String, nullable=False),
    Column("normalized_name", String, nullable=False),
    Column("brand", String),
    Column("ean", String),
    Column("kind", String, nullable=False),
    Column("price_cents", Integer, nullable=False),
    Column("regular_price_cents", Integer),
    Column("deposit_cents", Integer),
    Column("currency", String, nullable=False),
    Column("package_label", String),
    Column("unit_price_cents", Numeric(12, 2)),
    Column("unit_price_unit", String),
    Column("valid_from", Date, nullable=False),
    Column("valid_until", Date, nullable=False),
    Column("scope", String, nullable=False),
    Column("postal_code", String),
    Column("store_id", String),
    Column("requires_membership", Boolean, nullable=False),
    Column("conditions", String),
    Column("source_url", String, nullable=False),
    Column("observed_at", DateTime(timezone=True), nullable=False),
    Column("is_listed", Boolean, nullable=False, server_default="true"),
)
Index("price_catalog_lookup", prices.c.retailer, prices.c.kind, prices.c.valid_until)
Index("price_catalog_location", prices.c.postal_code, prices.c.store_id)
Index("price_catalog_ean", prices.c.ean)
versions = Table(
    "price_versions",
    metadata,
    Column("id", String, primary_key=True),
    Column("price_id", String, nullable=False),
    Column("source", String, nullable=False),
    Column("observed_at", DateTime(timezone=True), nullable=False),
    Column("event", String, nullable=False),
    Column("snapshot_json", String, nullable=False),
)
Index("price_versions_lookup", versions.c.price_id, versions.c.observed_at)
runs = Table(
    "price_source_runs",
    metadata,
    Column("source", String, primary_key=True),
    Column("last_attempt", DateTime(timezone=True), nullable=False),
    Column("last_success", DateTime(timezone=True)),
    Column("status", String, nullable=False),
    Column("message", String),
    Column("count", Integer, nullable=False),
)
area_stores = Table(
    "price_area_stores",
    metadata,
    Column("area_postal_code", String, primary_key=True),
    Column("retailer", String, primary_key=True),
    Column("store_id", String, primary_key=True),
    Column("name", String, nullable=False),
    Column("postal_code", String, nullable=False),
    Column("address", String, nullable=False),
    Column("latitude", Numeric(10, 7)),
    Column("longitude", Numeric(10, 7)),
    Column("distance_km", Numeric(8, 2)),
)


def normalize(value: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", value.casefold()) if not unicodedata.combining(c)
    )


def identity(source: str, p: PriceInput) -> str:
    import json

    key = [
        source,
        p.retailer,
        p.source_product_id,
        p.kind,
        p.scope,
        p.postal_code,
        p.store_id,
        p.valid_from.isoformat(),
    ]
    return str(uuid5(NAMESPACE_URL, json.dumps(key)))


class Database:
    def __init__(self, url: str):
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+psycopg://", 1)
        self.engine = create_engine(
            url, connect_args={"timeout": 60} if url.startswith("sqlite:") else {}
        )

    def initialize(self):
        metadata.create_all(self.engine)
        # create_all skips indexes on existing tables. Upgrade local SQLite installs;
        # production PostgreSQL uses the versioned SQL migrations.
        table = metadata.tables.get("external_price_observations")
        if self.engine.dialect.name == "sqlite" and table is not None:
            for index in table.indexes:
                if index.name == "external_prices_source_date":
                    index.create(self.engine, checkfirst=True)

    def _insert(self, table):
        return (pg_insert if self.engine.dialect.name == "postgresql" else sqlite_insert)(table)

    def record_run(self, source: str, status: str, count: int, message: str | None = None):
        values = dict(
            source=source,
            last_attempt=datetime.now(UTC),
            status=status,
            count=count,
            message=message,
        )
        if status == "ok":
            values["last_success"] = values["last_attempt"]
        stmt = self._insert(runs).values(**values)
        with self.engine.begin() as conn:
            conn.execute(stmt.on_conflict_do_update(index_elements=["source"], set_=values))

    def import_prices(self, source: str, items: list[PriceInput], *, snapshot: bool = False) -> int:
        from .catalog import products

        # Validate the entire batch before beginning; all writes share one transaction.
        with self.engine.begin() as conn:
            for item in items:
                values = item.model_dump()
                values.update(
                    id=identity(source, item),
                    source=source,
                    normalized_name=normalize(item.name),
                    source_url=str(item.source_url),
                    observed_at=item.observed_at.astimezone(UTC),
                    is_listed=True,
                )
                previous = (
                    conn.execute(
                        select(prices).where(prices.c.id == values["id"]).with_for_update()
                    )
                    .mappings()
                    .first()
                )
                if previous:
                    previous_time = previous["observed_at"]
                    previous_time = (
                        previous_time.astimezone(UTC)
                        if previous_time.tzinfo
                        else previous_time.replace(tzinfo=UTC)
                    )
                    if values["observed_at"] < previous_time:
                        continue
                event = None
                if not previous or any(
                    values[k] != previous[k] for k in values if k != "observed_at"
                ):
                    event = "added" if not previous else "changed"
                elif not conn.scalar(
                    select(versions.c.id).where(versions.c.price_id == values["id"]).limit(1)
                ):
                    event = "baseline"
                stmt = self._insert(prices).values(**values)
                applied = conn.scalar(
                    stmt.on_conflict_do_update(
                        index_elements=["id"],
                        set_=values,
                        where=stmt.excluded.observed_at >= prices.c.observed_at,
                    ).returning(prices.c.id)
                )
                if applied and event:
                    self._record_version(conn, values, event)
                if applied and item.ean:
                    product = self._insert(products).values(
                        ean=item.ean,
                        name=item.name,
                        normalized_name=normalize(item.name),
                        brand=item.brand,
                        package_label=item.package_label,
                        countries_json="[]",
                        reported_stores=None,
                        source="retailer_observation",
                        source_url=str(item.source_url),
                        source_updated_at=item.observed_at,
                        imported_at=datetime.now(UTC),
                    )
                    conn.execute(product.on_conflict_do_nothing(index_elements=["ean"]))
            if snapshot and items:
                snapshot_time = min(p.observed_at.astimezone(UTC) for p in items)
                removed = conn.execute(
                    select(prices).where(
                        prices.c.source == source,
                        prices.c.is_listed.is_(True),
                        prices.c.id.not_in([identity(source, p) for p in items]),
                        prices.c.observed_at <= snapshot_time,
                    )
                ).mappings()
                for row in removed:
                    self._record_version(
                        conn, {**row, "is_listed": False, "observed_at": snapshot_time}, "withdrawn"
                    )
                conn.execute(
                    update(prices)
                    .where(
                        prices.c.source == source,
                        prices.c.id.not_in([identity(source, p) for p in items]),
                        prices.c.observed_at <= snapshot_time,
                    )
                    .values(is_listed=False, observed_at=snapshot_time)
                )
        return len({identity(source, item) for item in items})

    def _record_version(self, conn, values: dict, event: str):
        snapshot = json.dumps(values, default=str, sort_keys=True)
        version_id = hashlib.sha256((snapshot + event).encode()).hexdigest()
        stmt = self._insert(versions).values(
            id=version_id,
            price_id=values["id"],
            source=values["source"],
            observed_at=values["observed_at"],
            event=event,
            snapshot_json=snapshot,
        )
        conn.execute(stmt.on_conflict_do_nothing(index_elements=["id"]))

    def price_history(self, price_id: str):
        with self.engine.connect() as conn:
            return [
                {
                    "event": row["event"],
                    "observed_at": row["observed_at"].isoformat(),
                    "price": json.loads(row["snapshot_json"]),
                }
                for row in conn.execute(
                    select(versions)
                    .where(versions.c.price_id == price_id)
                    .order_by(versions.c.observed_at.desc())
                ).mappings()
            ]

    def query(
        self,
        *,
        q: str | None,
        retailer: str | None,
        kind: str | None,
        on: date,
        postal_code: str | None,
        store_id: str | None,
        ean: str | None,
        include_membership: bool,
        max_age_days: int,
        limit: int,
        offset: int,
    ) -> PricePage:
        from .catalog import articles

        # Store-specific identity overrides a chain-wide mapping. Never replace
        # an explicit source barcode, including when it contradicts a mapping.
        mapped_ean = (
            select(articles.c.ean)
            .where(
                articles.c.retailer == prices.c.retailer,
                articles.c.source_product_id == prices.c.source_product_id,
                or_(
                    articles.c.store_id == "",
                    and_(prices.c.scope == "store", articles.c.store_id == prices.c.store_id),
                ),
            )
            .order_by((articles.c.store_id != "").desc())
            .limit(1)
            .correlate(prices)
            .scalar_subquery()
        )
        resolved_ean = func.coalesce(prices.c.ean, mapped_ean)
        filters = [
            prices.c.is_listed.is_(True),
            prices.c.valid_from <= on,
            prices.c.valid_until >= on,
            prices.c.observed_at >= datetime.now(UTC) - timedelta(days=max_age_days),
        ]
        for field, value in [("retailer", retailer), ("kind", kind)]:
            if value is not None:
                filters.append(prices.c[field] == value)
        if ean is not None:
            filters.append(resolved_ean == ean)
        if q:
            filters.append(prices.c.normalized_name.contains(normalize(q), autoescape=True))
        if not include_membership:
            filters.append(prices.c.requires_membership.is_(False))
        # Unfiltered browsing includes every scope, but location queries must never
        # return another branch's or postal area's prices.
        if postal_code or store_id:
            locations = [prices.c.scope == "chain_advertised"]
            if postal_code:
                locations.append(
                    and_(prices.c.scope == "postal_code", prices.c.postal_code == postal_code)
                )
                if not store_id:
                    nearby = (
                        select(area_stores.c.store_id)
                        .where(
                            area_stores.c.area_postal_code == postal_code,
                            area_stores.c.retailer == prices.c.retailer,
                        )
                        .correlate(prices)
                    )
                    locations.append(and_(prices.c.scope == "store", prices.c.store_id.in_(nearby)))
            if store_id:
                locations.append(and_(prices.c.scope == "store", prices.c.store_id == store_id))
            filters.append(or_(*locations))
        with self.engine.connect() as conn:
            total = conn.scalar(select(func.count()).select_from(prices).where(*filters))
            rows = (
                conn.execute(
                    select(prices, mapped_ean.label("mapped_ean"))
                    .where(*filters)
                    .order_by(prices.c.price_cents, prices.c.id)
                    .limit(limit)
                    .offset(offset)
                )
                .mappings()
                .all()
            )
        items = []
        for row in rows:
            data = dict(row)
            mapped = data.pop("mapped_ean")
            data["ean_origin"] = (
                "source" if data["ean"] else ("confirmed_mapping" if mapped else None)
            )
            data["ean"] = data["ean"] or mapped
            data["barcode_scope"] = barcode_scope(data["ean"]) if data["ean"] else None
            if data["observed_at"].tzinfo is None:
                data["observed_at"] = data["observed_at"].replace(tzinfo=UTC)
            data.pop("normalized_name")
            data.pop("is_listed")
            # Unknown deposit is not the same as zero deposit.
            data["checkout_price_cents"] = (
                data["price_cents"] + data["deposit_cents"]
                if data["deposit_cents"] is not None
                else None
            )
            items.append(Price(**data))
        return PricePage(items=items, total=total, limit=limit, offset=offset)

    def source_runs(self):
        with self.engine.connect() as conn:
            return {r["source"]: dict(r) for r in conn.execute(select(runs)).mappings()}

    def catalog_counts(self, on: date):
        with self.engine.connect() as conn:
            return {
                row["retailer"]: {
                    "price_count": row["price_count"],
                    "offer_count": row["offer_count"],
                }
                for row in conn.execute(
                    select(
                        prices.c.retailer,
                        func.count().label("price_count"),
                        func.count().filter(prices.c.kind == "offer").label("offer_count"),
                    )
                    .where(
                        prices.c.is_listed.is_(True),
                        prices.c.valid_from <= on,
                        prices.c.valid_until >= on,
                        prices.c.requires_membership.is_(False),
                        prices.c.observed_at >= datetime.now(UTC) - timedelta(days=7),
                    )
                    .group_by(prices.c.retailer)
                ).mappings()
            }

    def save_area_stores(self, postal_code: str, retailer: str, stores: list[dict]):
        from sqlalchemy import delete

        with self.engine.begin() as conn:
            conn.execute(
                delete(area_stores).where(
                    area_stores.c.area_postal_code == postal_code,
                    area_stores.c.retailer == retailer,
                )
            )
            for store in stores:
                conn.execute(
                    area_stores.insert().values(
                        area_postal_code=postal_code,
                        retailer=retailer,
                        store_id=str(store["wwIdent"]),
                        name=store["marketName"],
                        postal_code=store["zipCode"],
                        address=f"{store['streetWithHouseNumber']}, {store['city']}",
                        latitude=store.get("latitude"),
                        longitude=store.get("longitude"),
                        distance_km=store.get("distance_km"),
                    )
                )

    def stores_for_area(self, postal_code: str):
        with self.engine.connect() as conn:
            return [
                dict(r)
                for r in conn.execute(
                    select(area_stores)
                    .where(
                        area_stores.c.area_postal_code == postal_code,
                    )
                    .order_by(area_stores.c.distance_km)
                ).mappings()
            ]
