"""External price observations without invented geographical scope or validity."""

import csv
import fcntl
import hashlib
import json
import os
import re
import time
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import Column, Index, Integer, String, Table, Text, func, select

from .barcodes import barcode_scope, valid_ean
from .catalog import ProductInput, ProductRepository
from .database import Database, metadata, normalize
from .sources import SourceError

observations = Table(
    "external_price_observations",
    metadata,
    Column("id", String, primary_key=True),
    Column("source", String, nullable=False),
    Column("retailer", String, nullable=False),
    Column("ean", String),
    Column("name", String, nullable=False),
    Column("normalized_name", String, nullable=False),
    Column("price_cents", Integer, nullable=False),
    Column("price_date", String),
    Column("postal_code", String),
    Column("store_id", String),
    Column("payload_json", Text, nullable=False),
)
Index("external_prices_ean_date", observations.c.ean, observations.c.price_date)
Index("external_prices_source", observations.c.source)
Index("external_prices_source_date", observations.c.source, observations.c.price_date)


def cents(value):
    amount = Decimal(str(value).replace(",", "."))
    if not amount.is_finite() or amount < 0 or amount > 1_000_000:
        raise ValueError("Invalid price")
    return int((amount * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def iso_date(value):
    return date.fromisoformat(str(value)[:10]).isoformat() if value else None


class ObservationRepository:
    def __init__(self, db: Database):
        self.db = db

    def save(self, entries):
        rows = []
        for entry in entries:
            entry = dict(entry)
            code = str(entry.get("ean") or "")
            entry["ean"] = code if valid_ean(code) else None
            entry["barcode_scope"] = barcode_scope(code) if entry["ean"] else None
            entry.setdefault("currency", "EUR")
            # Import timestamps never replace the date the price was observed.
            entry["imported_at"] = datetime.now(UTC).isoformat()
            identity = {k: v for k, v in entry.items() if k != "imported_at"}
            key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
            entry["id"] = key
            rows.append(
                dict(
                    id=key,
                    source=entry["source"],
                    retailer=entry["retailer"],
                    ean=entry["ean"],
                    name=entry["name"],
                    normalized_name=normalize(entry["name"]),
                    price_cents=entry["price_cents"],
                    price_date=entry.get("price_date"),
                    postal_code=entry.get("postal_code"),
                    store_id=entry.get("store_id"),
                    payload_json=json.dumps(entry),
                )
            )
        if rows:
            with self.db.engine.begin() as conn:
                stmt = self.db._insert(observations).on_conflict_do_nothing(index_elements=["id"])
                for start in range(0, len(rows), 500):
                    conn.execute(stmt, rows[start : start + 500])
        return len(rows)

    def query(
        self, q=None, ean=None, retailer=None, source=None, postal_code=None, limit=50, offset=0
    ):
        filters = []
        for column, value in [
            (observations.c.ean, ean),
            (observations.c.retailer, retailer),
            (observations.c.source, source),
            (observations.c.postal_code, postal_code),
        ]:
            if value:
                filters.append(column == value)
        if q:
            filters.append(observations.c.normalized_name.contains(normalize(q), autoescape=True))
        today = datetime.now(ZoneInfo("Europe/Berlin")).date().isoformat()
        with self.db.engine.connect() as conn:
            total = conn.scalar(select(func.count()).select_from(observations).where(*filters))
            rows = conn.execute(
                select(observations.c.payload_json)
                .where(*filters)
                .order_by(observations.c.price_date.desc().nulls_last(), observations.c.id)
                .limit(limit)
                .offset(offset)
            ).scalars()
            items = []
            for raw in rows:
                item = json.loads(raw)
                item["date_status"] = (
                    "undated"
                    if not item.get("price_date")
                    else "observed_today"
                    if item["price_date"] == today
                    else "historical"
                    if item["price_date"] < today
                    else "future"
                )
                item["current_price_verified"] = False
                if item.get("valid_from") and item.get("valid_until"):
                    item["offer_status"] = (
                        "upcoming"
                        if today < item["valid_from"]
                        else "expired"
                        if today > item["valid_until"]
                        else "within_validity"
                    )
                items.append(item)
        return dict(
            items=items,
            total=total,
            limit=limit,
            offset=offset,
            note="Dated source observations, not guaranteed current local shelf prices",
        )

    def status(self):
        with self.db.engine.connect() as conn:
            rows = conn.execute(
                select(
                    observations.c.source,
                    func.count().label("count"),
                    func.max(observations.c.price_date).label("latest_price_date"),
                ).group_by(observations.c.source)
            ).mappings()
            result = {"sources": [dict(r) for r in rows]}
        checkpoint = (
            Path(os.getenv("PRICEWATCH_CATALOG_DIR", "./data/catalog")) / "dm-progress.json"
        )
        if checkpoint.exists():
            try:
                result["dm_progress"] = dm_summary(json.loads(checkpoint.read_text()))
            except (ValueError, KeyError):
                result["dm_progress"] = {"error": "Saved dm progress could not be read"}
        return result

    def import_dataset(self, path):
        entries, rejected = [], 0
        with Path(path).open(newline="", encoding="utf-8-sig") as handle:
            for row in csv.DictReader(handle):
                try:
                    if not row["product_name"].strip() or not row["retailer"].strip():
                        raise ValueError("Missing product or retailer")
                    entries.append(
                        dict(
                            source="german_supermarket_prices",
                            upstream_source=row["source"],
                            retailer=row["retailer"],
                            name=row["product_name"],
                            ean=row["ean_barcode"],
                            price_cents=cents(row["price_eur"]),
                            price_date=iso_date(row["price_date"]),
                            collected_at=iso_date(row["collected_at"]),
                            kind="offer" if row["source"] == "marktguru-offers" else "unknown",
                            scope="unknown",
                            valid_from=None,
                            valid_until=None,
                            source_url="https://github.com/loukesio/german-supermarket-prices",
                            license="ODbL-1.0",
                            category=row["category"],
                            raw_barcode=row["ean_barcode"],
                        )
                    )
                except (ValueError, InvalidOperation, KeyError):
                    rejected += 1
        return {"processed": self.save(entries), "rejected": rejected}

    def import_rewe(self, path, snapshot_date, region, source_url):
        entries, products, rejected = [], [], 0
        with Path(path).open(newline="", encoding="utf-8-sig") as handle:
            for row in csv.DictReader(handle):
                try:
                    name = row["name"].strip()
                    if not name:
                        raise ValueError("Missing name")
                    code = row["ean"]
                    entries.append(
                        dict(
                            source="rewe_price_data",
                            retailer="REWE",
                            name=name,
                            ean=code,
                            raw_barcode=code,
                            price_cents=cents(row["price"]),
                            price_date=iso_date(snapshot_date),
                            region=region,
                            scope="region_unknown_store",
                            kind="offer" if row["sale"].lower() == "true" else "regular",
                            package_label=row["grammage"],
                            brand=row["brand"],
                            category=row["category"],
                            source_url=source_url,
                            valid_from=None,
                            valid_until=None,
                        )
                    )
                    if valid_ean(code):
                        products.append(
                            ProductInput(
                                ean=code,
                                name=name[:300],
                                brand=None if row["brand"] == "NA" else row["brand"][:300],
                                package_label=row["grammage"][:300] or None,
                                countries=["en:germany"],
                                categories=[row["category"]][:100],
                                reported_stores="REWE",
                                source_url=source_url,
                            )
                        )
                except (ValueError, InvalidOperation, KeyError):
                    rejected += 1
        repo = ProductRepository(self.db)
        for start in range(0, len(products), 500):
            repo.upsert(products[start : start + 500], source="rewe_price_data")
        return {"processed": self.save(entries), "rejected": rejected}


def get(client, url, **kwargs):
    """Bounded retries for public feeds; no authentication challenge bypass."""
    for attempt in range(4):
        response = client.get(url, **kwargs)
        if response.status_code not in (429, 502, 503, 504):
            response.raise_for_status()
            return response
        time.sleep(2**attempt)
    raise SourceError(f"{url.split('?')[0]}: HTTP {response.status_code}")


def sync_external(db, directory, selected="all"):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "external-sync.lock").open("w") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise SourceError("External source import already running") from exc
        return _sync_external(db, directory, selected)


def _sync_external(db, directory, selected):
    repo = ObservationRepository(db)
    result = {}
    with httpx.Client(
        timeout=60,
        follow_redirects=True,
        headers={"User-Agent": "PriceWatch/0.1 public price research"},
    ) as client:
        for source in ["dataset", "rewe", "dm", "open_prices", "marktguru"]:
            if selected not in ("all", source):
                continue
            try:
                stats = globals()["sync_" + source](client, repo, directory)
                result[source] = stats
                db.record_run(
                    "external_" + source,
                    "running"
                    if stats.get("pending")
                    else "error"
                    if stats.get("partial")
                    else "ok",
                    stats.get("processed", 0),
                    json.dumps(stats)[:2000],
                )
            except (httpx.HTTPError, SourceError, ValueError, KeyError) as exc:
                # Other independent sources continue after one inaccessible feed.
                result[source] = {"error": str(exc)[:500]}
                db.record_run("external_" + source, "error", 0, str(exc)[:500])
    return result


def sync_dataset(client, repo, directory):
    url = (
        "https://raw.githubusercontent.com/loukesio/german-supermarket-prices/main/data/prices.csv"
    )
    response = get(client, url)
    path = directory / "german-supermarket-prices.csv"
    path.write_bytes(response.content)
    return repo.import_dataset(path)


def sync_rewe(client, repo, directory):
    home = "https://rewe.nicoo.org/"
    html = get(client, home).text
    files = re.findall(r'href="(/\d{4}-\d{2}-\d{2}_(?:bavaria|schleswig-holstein)\.csv)"', html)
    processed = 0
    snapshots = []
    for region in ["bavaria", "schleswig-holstein"]:
        latest = max((p for p in files if p.endswith("_" + region + ".csv")), default=None)
        if latest is None:
            continue
        url = urljoin(home, latest)
        path = directory / latest.lstrip("/")
        path.write_bytes(get(client, url).content)
        stats = repo.import_rewe(path, latest[1:11], region, url)
        processed += stats["processed"]
        snapshots.append({"region": region, "date": latest[1:11], **stats})
    return {"processed": processed, "snapshots": snapshots}


def sync_dm(client, repo, directory):
    url = "https://product-search.services.dmtech.com/de/search"
    state_path = directory / "dm-progress.json"
    now = datetime.now(UTC)
    state = json.loads(state_path.read_text()) if state_path.exists() else None
    if state and state["phase"] == "completed":
        if now < datetime.fromisoformat(state["refresh_after"]):
            return dm_summary(state, processed=0)
        state = None
    if state is None:
        state = {
            "version": 1,
            "phase": "scanning",
            "started_at": now.isoformat(),
            "jobs": [{"filters": {}, "page": 0}],
            "seen": [],
            "requests": 0,
            "expected": None,
            "capped": [],
            "next_retry_at": None,
            "last_error": None,
        }
    if state.get("next_retry_at") and now < datetime.fromisoformat(state["next_retry_at"]):
        return dm_summary(state, processed=0)
    processed, seen = 0, set(state["seen"])
    today = datetime.now(ZoneInfo("Europe/Berlin")).date().isoformat()

    def consume(data):
        batch, products = [], []
        for product in data.get("products", []):
            key = str(product["dan"])
            if key in seen:
                continue
            seen.add(key)
            tile = product["tileData"]
            tracking = tile.get("trackingData", {})
            code = str(product.get("gtin", ""))
            price = tracking.get("price")
            if price is None:
                continue
            source_url = "https://www.dm.de/" + normalize(product["title"]).replace(" ", "-")
            source_url += "-p" + code + ".html"
            batch.append(
                dict(
                    source="dm_website",
                    retailer="dm",
                    ean=code,
                    name=product["title"],
                    source_product_id=key,
                    brand=product.get("brandName"),
                    price_cents=cents(price),
                    price_date=today,
                    scope="online",
                    kind="unknown",
                    valid_from=None,
                    valid_until=None,
                    source_url=source_url,
                    api_source_url=str(url),
                    package_label=tile.get("price", {}).get("tileInfos"),
                )
            )
            if valid_ean(code):
                products.append(
                    ProductInput(
                        ean=code,
                        name=product["title"][:300],
                        brand=product.get("brandName"),
                        countries=["en:germany"],
                        reported_stores="dm",
                        source_url=source_url,
                        categories=tracking.get("categories", [])[:100],
                    )
                )
        count = repo.save(batch)
        ProductRepository(repo.db).upsert(products, source="retailer_observation")
        return count

    # Persist only after the corresponding price/product writes have committed.
    # A crash before checkpointing replays the same page safely via deduplication.
    for request_index in range(10):
        if not state["jobs"]:
            state["phase"] = "completed"
            state["refresh_after"] = (datetime.now(UTC) + timedelta(days=1)).isoformat()
            save_dm_checkpoint(state_path, state)
            break
        job = state["jobs"][0]
        params = {"query": "", "pageSize": 100, "currentPage": job["page"], **job["filters"]}
        try:
            response = client.get(url, params=params)
            if response.status_code in (429, 401, 403, 502, 503, 504):
                delay = retry_delay(
                    response.headers.get("Retry-After"),
                    default=86400 if response.status_code in (401, 403) else 3600,
                )
                state.update(
                    phase="cooldown",
                    last_error=f"HTTP {response.status_code}",
                    next_retry_at=(datetime.now(UTC) + timedelta(seconds=delay)).isoformat(),
                )
                save_dm_checkpoint(state_path, state)
                break
            response.raise_for_status()
            data = response.json()
            if not isinstance(data.get("products"), list) or "totalPages" not in data:
                raise SourceError("dm response lacks products or pagination")
            processed += consume(data)
        except (httpx.HTTPError, ValueError, SourceError) as exc:
            state.update(
                phase="cooldown",
                last_error=str(exc)[:300],
                next_retry_at=(datetime.now(UTC) + timedelta(hours=1)).isoformat(),
            )
            save_dm_checkpoint(state_path, state)
            break
        state.update(phase="scanning", last_error=None, next_retry_at=None)
        state["requests"] += 1
        if state["expected"] is None:
            state["expected"] = data.get("count")
            for facet in data.get("facets", []):
                if facet["key"] in ("categoryNames", "brandName"):
                    state["jobs"].extend(
                        {"filters": {facet["key"]: value["name"]}, "page": 0}
                        for value in facet.get("values", [])
                    )
        if job["page"] == 0 and data.get("count", 0) > 1000:
            state["capped"].append(job["filters"])
        if not data["products"] or job["page"] + 1 >= data["totalPages"]:
            state["jobs"].pop(0)
        else:
            job["page"] += 1
        state["seen"] = sorted(seen)
        save_dm_checkpoint(state_path, state)
        if request_index < 9:
            time.sleep(3)
    return dm_summary(state, processed)


def retry_delay(value, default=3600):
    """Honor Retry-After seconds or HTTP date, with a minimum five minute pause."""
    try:
        delay = int(value)
    except (TypeError, ValueError):
        try:
            delay = int((parsedate_to_datetime(value) - datetime.now(UTC)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            delay = default
    return max(300, min(delay, 86400))


def save_dm_checkpoint(path, state):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state), encoding="utf-8")
    temporary.replace(path)


def dm_summary(state, processed=0):
    return {
        "processed": processed,
        "phase": state["phase"],
        "unique_articles": len(state["seen"]),
        "reported_index_count": state["expected"],
        "requests": state["requests"],
        "remaining_queries": len(state["jobs"]),
        "next_page": state["jobs"][0]["page"] if state["jobs"] else None,
        "next_retry_at": state.get("next_retry_at"),
        "last_error": state.get("last_error"),
        "capped_queries": len(state["capped"]),
        "pending": state["phase"] != "completed",
        "partial": len(state["seen"]) < (state["expected"] or 0),
        "coverage": "Online search, partitioned by category/brand; not branch shelf prices",
    }


def sync_open_prices(client, repo, directory):
    base = "https://prices.openfoodfacts.org/api/v1/"
    locations = []
    page = 1
    while True:
        data = get(
            client,
            base + "locations",
            params={
                "osm_address_country__like": "Deutschland",
                "price_count__gte": 1,
                "size": 100,
                "page": page,
            },
        ).json()
        locations.extend(
            p["id"] for p in data["items"] if p.get("osm_address_country_code") == "DE"
        )
        if page >= data["pages"]:
            break
        page += 1
        time.sleep(0.2)
    processed = 0
    for start in range(0, len(locations), 30):
        page = 1
        while True:
            data = get(
                client,
                base + "prices",
                params={
                    "location_id__in": ",".join(map(str, locations[start : start + 30])),
                    "currency": "EUR",
                    "size": 100,
                    "page": page,
                },
            ).json()
            entries, products = [], []
            for item in data["items"]:
                loc = item.get("location") or {}
                if loc.get("osm_address_country_code") != "DE" or item.get("duplicate_of"):
                    continue
                product = item.get("product") or {}
                name = product.get("product_name") or item.get("product_name")
                code = str(item.get("product_code") or "")
                # Unknown names/codes remain visible; no guessed retailer identity.
                name = name or item.get("category_tag") or "Produkt " + (code or str(item["id"]))
                source_url = "https://prices.openfoodfacts.org/prices/" + str(item["id"])
                entries.append(
                    dict(
                        source="open_prices",
                        source_product_id=str(item["id"]),
                        ean=code,
                        name=name,
                        retailer=loc.get("osm_brand") or loc.get("osm_name") or "Unbekannt",
                        price_cents=cents(item["price"]),
                        price_date=iso_date(item["date"]),
                        scope="store",
                        store_id="open_prices:" + str(loc["id"]),
                        postal_code=loc.get("osm_address_postcode"),
                        location=loc,
                        kind="discounted" if item["price_is_discounted"] else "unknown",
                        price_without_discount=item.get("price_without_discount"),
                        discount_type=item.get("discount_type"),
                        price_per=item.get("price_per"),
                        package_label=product.get("quantity"),
                        source_url=source_url,
                        proof_id=item.get("proof_id"),
                        license="ODbL-1.0",
                        valid_from=None,
                        valid_until=None,
                    )
                )
                if valid_ean(code) and product.get("product_name"):
                    products.append(
                        ProductInput(
                            ean=code,
                            name=product["product_name"][:300],
                            brand=(product.get("brands") or "")[:300] or None,
                            package_label=(product.get("quantity") or "")[:300] or None,
                            countries=["en:germany"],
                            source_url=source_url,
                            categories=product.get("categories_tags", [])[:100],
                        )
                    )
            processed += repo.save(entries)
            ProductRepository(repo.db).upsert(products, source="open_prices")
            if page >= data["pages"]:
                break
            page += 1
            time.sleep(0.2)
    return {"processed": processed, "locations": len(locations)}


def sync_marktguru(client, repo, directory):
    html = get(client, "https://www.marktguru.de").text
    config = None
    for block in re.findall(
        r'<script[^>]*type=["\']application/json["\'][^>]*>(.*?)</script>', html, re.S
    ):
        try:
            candidate = json.loads(block).get("config", {})
            if candidate.get("apiKey") and candidate.get("clientKey"):
                config = candidate
                break
        except ValueError:
            pass
    if config is None:
        raise SourceError("Marktguru public web configuration unavailable")
    # Search terms derived from every promotional category in the provided dataset.
    with (directory / "german-supermarket-prices.csv").open(encoding="utf-8") as handle:
        terms = sorted(
            {
                r["category"].removeprefix("Angebot · ").strip()
                for r in csv.DictReader(handle)
                if r["source"] == "marktguru-offers"
            }
        )
    entries, seen, capped = [], set(), 0
    for term in terms:
        if not term:
            continue
        data = get(
            client,
            "https://api.marktguru.de/api/v1/offers/search",
            params={
                "as": "web",
                "limit": 100,
                "q": term,
                "zipCode": "85567",
            },
            headers={"x-apikey": config["apiKey"], "x-clientkey": config["clientKey"]},
        ).json()
        capped += int(data.get("totalResults", 0) > 100)
        for item in data.get("results") or []:
            if str(item.get("id")) in seen or item.get("price") is None:
                continue
            seen.add(str(item["id"]))
            for advertiser in item.get("advertisers") or []:
                periods = item.get("validityDates") or [{}]
                for period in periods:
                    entries.append(
                        dict(
                            source="marktguru",
                            retailer=advertiser.get("name") or "Unbekannt",
                            name=(item.get("product") or {}).get("name")
                            or item.get("description")
                            or "Angebot " + str(item["id"]),
                            ean=None,
                            price_cents=cents(item["price"]),
                            kind="offer",
                            scope="postal_code",
                            postal_code="85567",
                            price_date=None,
                            valid_from=iso_date(period.get("from")),
                            valid_until=iso_date(period.get("to")),
                            description=item.get("description"),
                            volume=item.get("volume"),
                            quantity=item.get("quantity"),
                            unit=item.get("unit"),
                            source_url="https://www.marktguru.de/offers/" + str(item["id"]),
                        )
                    )
        time.sleep(0.3)
    return {
        "processed": repo.save(entries),
        "queries": len(terms),
        "capped_queries": capped,
        "postal_code": "85567",
        "coverage": "Category search, not complete retailer stock",
    }
