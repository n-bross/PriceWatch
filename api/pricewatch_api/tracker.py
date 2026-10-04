"""Persistent polling, catalog change history and queued receipt rechecks."""

import fcntl
import hashlib
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import Column, DateTime, String, Table, Text, select, update

from .database import Database, area_stores, metadata, prices, versions
from .flyers import FlyerRepository, flyers
from .ingestion import AUTOMATIC, sync_source
from .receipts import ReceiptRepository, ReceiptReview
from .sources import SourceError

watches = Table(
    "price_source_watches",
    metadata,
    Column("id", String, primary_key=True),
    Column("retailer", String, nullable=False),
    Column("mode", String, nullable=False),
    Column("url", String, nullable=False),
    Column("checked_at", DateTime(timezone=True), nullable=False),
    Column("changed_at", DateTime(timezone=True)),
    Column("fingerprint", String),
    Column("etag", String),
    Column("last_modified", String),
    Column("status", String, nullable=False),
    Column("message", Text),
)
refresh_requests = Table(
    "price_receipt_rechecks",
    metadata,
    Column("receipt_id", String, primary_key=True),
    Column("retailer", String, nullable=False),
    Column("postal_code", String),
    Column("requested_at", DateTime(timezone=True), nullable=False),
    Column("processed_at", DateTime(timezone=True)),
    Column("status", String, nullable=False),
    Column("message", Text),
)
# Read-only watches for retailers without a verified automatic product adapter.
WATCH_URLS = {
    "rewe": "https://www.rewe.de/marktseite/grafing/461766/rewe-markt-leonhardstr-5-a/",
    "netto": "https://www.netto-online.de/ueber-netto/Online-Prospekte.chtm/1013",
    "edeka": "https://www.edeka.de/angebote/",
    "norma": "https://www.norma-online.de/de/angebote/onlineprospekt/",
    "globus": "https://produkte.globus.de/angebote-der-woche/",
    "tegut": "https://mittelhessen.tegut.com/",
    "hit": "https://www.hit.de/angebote.html",
    "combi": "https://www.combi.de/angebote",
    "nahkauf": "https://www.nahkauf.de/home/",
    "alnatura": "https://www.alnatura.de/de-de/angebote/",
    "netto_dog": "https://netto.de/prospekte/",
}


def digest(value):
    return hashlib.sha256(json.dumps(value, default=str, sort_keys=True).encode()).hexdigest()


def queue_recheck(db: Database, receipt_id: str, retailer: str, postal_code: str | None):
    values = dict(
        receipt_id=receipt_id,
        retailer=retailer,
        postal_code=postal_code,
        requested_at=datetime.now(UTC),
        processed_at=None,
        status="queued",
        message=None,
    )
    stmt = db._insert(refresh_requests).values(**values)
    with db.engine.begin() as conn:
        conn.execute(stmt.on_conflict_do_update(index_elements=["receipt_id"], set_=values))


class Tracker:
    def __init__(self, db: Database):
        self.db = db

    def state(self):
        with self.db.engine.connect() as conn:
            return [
                dict(row) for row in conn.execute(select(watches).order_by(watches.c.id)).mappings()
            ]

    def record(
        self,
        key,
        retailer,
        mode,
        url,
        fingerprint,
        status,
        message=None,
        etag=None,
        last_modified=None,
    ):
        now = datetime.now(UTC)
        with self.db.engine.begin() as conn:
            old = conn.execute(select(watches).where(watches.c.id == key)).mappings().first()
            values = dict(
                id=key,
                retailer=retailer,
                mode=mode,
                url=url,
                checked_at=now,
                status=status,
                message=message,
                etag=etag,
                last_modified=last_modified,
            )
            if fingerprint is not None:
                values["fingerprint"] = fingerprint
                if not old or fingerprint != old["fingerprint"]:
                    values["changed_at"] = now
            stmt = self.db._insert(watches).values(**values)
            conn.execute(stmt.on_conflict_do_update(index_elements=["id"], set_=values))

    def sync(self, source: str, postal_code=None):
        key = f"penny:area:{postal_code}" if source == "penny" else source
        try:
            result = sync_source(self.db, source, postal_code)
            with self.db.engine.connect() as conn:
                filters = [prices.c.retailer == source, prices.c.is_listed.is_(True)]
                if source == "penny" and postal_code:
                    stores = select(area_stores.c.store_id).where(
                        area_stores.c.area_postal_code == postal_code,
                        area_stores.c.retailer == "penny",
                    )
                    filters.append(prices.c.store_id.in_(stores))
                rows = [
                    dict(r)
                    for r in conn.execute(
                        select(prices).where(*filters).order_by(prices.c.id)
                    ).mappings()
                ]
            for row in rows:
                row.pop("observed_at", None)
            fingerprint = digest(rows)
            old = next((w for w in self.state() if w["id"] == key), None)
            self.record(
                key,
                source,
                "automatic",
                rows[0]["source_url"] if rows else "",
                fingerprint,
                "changed" if not old or old["fingerprint"] != fingerprint else "unchanged",
                f"{result['processed']} current/future offer records checked",
            )
            return True
        except Exception as exc:
            self.record(key, source, "automatic", "", None, "error", str(exc)[:500])
            return False

    def watch_page(self, retailer, url, old):
        headers = {}
        if old and old.get("etag"):
            headers["If-None-Match"] = old["etag"]
        if old and old.get("last_modified"):
            headers["If-Modified-Since"] = old["last_modified"]
        try:
            with httpx.Client(timeout=12, follow_redirects=True) as client:
                with client.stream("GET", url, headers=headers) as response:
                    if response.status_code == 304 and old:
                        return (
                            retailer,
                            url,
                            old["fingerprint"],
                            "unchanged",
                            "Not modified; no product adapter",
                            old.get("etag"),
                            old.get("last_modified"),
                        )
                    if response.status_code in [401, 403]:
                        blocked_body = bytearray()
                        for chunk in response.iter_bytes(65536):
                            blocked_body.extend(chunk)
                            if len(blocked_body) >= 4 * 1024 * 1024:
                                break
                        text = blocked_body.decode(errors="replace").lower()
                        reason = f"HTTP {response.status_code}: Serverabruf verweigert"
                        if "waf challenge" in text or "bot protection" in text:
                            reason += "; Händlerseite nennt WAF Challenge / Bot protection"
                        return retailer, url, None, "blocked", reason, None, None
                    response.raise_for_status()
                    content = bytearray()
                    for chunk in response.iter_bytes(65536):
                        content.extend(chunk)
                        if len(content) > 4 * 1024 * 1024:
                            raise SourceError("Watch page exceeds 4 MiB")
                    soup = BeautifulSoup(bytes(content), "html.parser")
                    links = sorted(
                        {
                            a["href"]
                            for a in soup.select("a[href]")
                            if re.search(r"pdf|prospekt|leaflet|publitas", a["href"], re.I)
                        }
                    )
                    for node in soup(["script", "style"]):
                        node.decompose()
                    fingerprint = digest([" ".join(soup.stripped_strings), links])
                    status = (
                        "changed_unparsed"
                        if not old or old["fingerprint"] != fingerprint
                        else "unchanged"
                    )
                    return (
                        retailer,
                        url,
                        fingerprint,
                        status,
                        "Website watch only; change is not proof of a new offer or price",
                        response.headers.get("etag"),
                        response.headers.get("last-modified"),
                    )
        except Exception as exc:
            return (
                retailer,
                url,
                None,
                "blocked"
                if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in [401, 403]
                else "error",
                str(exc)[:500],
                None,
                None,
            )

    def sync_lidl(self, on=None, key="lidl"):
        from .flyer_sources import discover_lidl_flyer, download_lidl_pdf

        try:
            info = discover_lidl_flyer(on)
            url = str(info.source_url)
            with httpx.Client(timeout=15, follow_redirects=True) as client:
                response = client.head(url)
                etag = response.headers.get("etag") if response.is_success else None
                modified = response.headers.get("last-modified") if response.is_success else None
                size = response.headers.get("content-length") if response.is_success else None
            fingerprint = digest([info.model_dump(mode="json"), etag, modified, size])
            old = next((w for w in self.state() if w["id"] == key), None)
            with self.db.engine.connect() as conn:
                saved = (
                    conn.execute(select(flyers).where(flyers.c.source_url == url))
                    .mappings()
                    .first()
                )
            # If the CDN has no validators, download at least every six hours.
            recent = saved and datetime.now(UTC) - saved["observed_at"].replace(
                tzinfo=UTC
            ) < timedelta(hours=6)
            skip = (
                old and old["fingerprint"] == fingerprint and saved and (etag or modified or recent)
            )
            if skip:
                status = "unchanged"
            else:
                repository = FlyerRepository(
                    self.db, os.getenv("PRICEWATCH_FLYER_DIR", "./data/flyers")
                )
                result = repository.import_pdf(info, download_lidl_pdf(url))
                status = "changed"
                self.db.record_run(key, "ok", result["pages"])
            self.record(
                key,
                "lidl",
                "flyer_search",
                url,
                fingerprint,
                status,
                "Official PDF text; product prices require verification",
                etag,
                modified,
            )
            return True
        except Exception as exc:
            if on and isinstance(exc, SourceError) and "No currently valid" in str(exc):
                self.record(
                    key,
                    "lidl",
                    "flyer_search",
                    "",
                    None,
                    "not_published",
                    "Upcoming flyer not linked yet",
                )
                return True
            self.record(key, "lidl", "flyer_search", "", None, "error", str(exc)[:500])
            return False

    def run(self):
        # One worker per database, also covering HTTP-triggered runs.
        lock_path = Path(
            os.getenv(
                "PRICEWATCH_TRACKER_LOCK",
                f"/tmp/pricewatch-{digest(str(self.db.engine.url))[:16]}.lock",
            )
        )
        with lock_path.open("w") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return {"status": "already_running"}
            with self.db.engine.connect() as conn:
                areas = set(
                    conn.scalars(
                        select(area_stores.c.area_postal_code)
                        .where(area_stores.c.retailer == "penny")
                        .distinct()
                    )
                )
                queued = [
                    dict(r)
                    for r in conn.execute(
                        select(refresh_requests).where(refresh_requests.c.status == "queued")
                    ).mappings()
                ]
            areas.add(os.getenv("PRICEWATCH_DEFAULT_POSTAL_CODE", "85567"))
            areas.update(
                q["postal_code"] for q in queued if q["postal_code"] and q["retailer"] == "penny"
            )
            outcomes = {}
            for source in AUTOMATIC:
                if source == "penny":
                    for area in sorted(areas):
                        outcomes[f"penny:area:{area}"] = self.sync("penny", area)
                else:
                    outcomes[source] = self.sync(source)
            outcomes["lidl"] = self.sync_lidl()
            today = datetime.now(UTC).date()
            outcomes["lidl:upcoming"] = self.sync_lidl(
                today + timedelta(days=7 - today.weekday()), "lidl:upcoming"
            )
            old = {w["id"]: w for w in self.state()}
            with ThreadPoolExecutor(max_workers=4) as pool:
                results = list(
                    pool.map(
                        lambda pair: self.watch_page(pair[0], pair[1], old.get(pair[0])),
                        WATCH_URLS.items(),
                    )
                )
            for retailer, url, fingerprint, status, message, etag, modified in results:
                self.record(
                    retailer,
                    retailer,
                    "watch_only",
                    url,
                    fingerprint,
                    status,
                    message,
                    etag,
                    modified,
                )
            repository = ReceiptRepository(
                self.db, os.getenv("PRICEWATCH_RECEIPT_DIR", "./data/receipts")
            )
            for request in queued:
                key = (
                    f"penny:area:{request['postal_code']}"
                    if request["retailer"] == "penny"
                    else request["retailer"]
                )
                if key in outcomes and not outcomes[key]:
                    continue  # Keep queued after a failed source refresh.
                try:
                    receipt = repository.get(request["receipt_id"])
                    review = ReceiptReview(**{**receipt["metadata"], "lines": receipt["lines"]})
                    repository.review(receipt["id"], review, queue=False)
                    comparisons = repository.get(receipt["id"])["comparisons"]
                    unresolved = any(
                        c["status"] not in ["match", "advertised_match"] for c in comparisons
                    )
                    status = "unresolved" if unresolved else "resolved"
                    message = (
                        "Source checked and receipt compared again"
                        if key in outcomes
                        else "No automatic source adapter; manual verification needed"
                    )
                except KeyError:
                    status, message = "deleted", "Receipt removed"
                with self.db.engine.begin() as conn:
                    conn.execute(
                        update(refresh_requests)
                        .where(refresh_requests.c.receipt_id == request["receipt_id"])
                        .values(status=status, message=message, processed_at=datetime.now(UTC))
                    )
            return {
                "status": "ok" if all(outcomes.values()) else "partial_error",
                "automatic_sources": outcomes,
                "watched_pages": len(WATCH_URLS),
                "receipt_rechecks": len(queued),
            }

    def changes(self, limit=50):
        with self.db.engine.connect() as conn:
            return [
                {
                    "event": r["event"],
                    "observed_at": r["observed_at"].isoformat(),
                    "price": json.loads(r["snapshot_json"]),
                }
                for r in conn.execute(
                    select(versions).order_by(versions.c.observed_at.desc()).limit(limit)
                ).mappings()
            ]
