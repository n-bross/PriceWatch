"""Bounded REWE shop imports; pickup observations never become in-store offers."""

import argparse
import fcntl
import json
import os
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode, urljoin
from zoneinfo import ZoneInfo

import httpx

from .barcodes import source_ean
from .conditional_fetch import ConditionalFetcher, SourceCooldown, atomic_json
from .database import Database
from .observations import ObservationRepository
from .rewe_browser import BrowserProduct

SOURCE = "rewe_shop_pickup"
URL = "https://www.rewe.de/shop/api/products"
INTERVAL = timedelta(hours=6)


def parse_page(payload, market_id, postal_code, observed_at, page):
    search = payload["search"]
    if search.get("marketCode") != market_id or search.get("serviceTypes") != ["PICKUP"]:
        raise ValueError("REWE response does not confirm requested market and pickup channel")
    pagination = payload["pagination"]
    total_pages = pagination["totalPages"]
    if pagination["page"] != page or type(total_pages) is not int or total_pages < page:
        raise ValueError("Invalid REWE pagination")
    products = payload["_embedded"]["products"]
    if not isinstance(products, list) or not products:
        raise ValueError("REWE returned no products; existing observations retained")
    entries = []
    for product in products:
        for article in product["_embedded"]["articles"]:
            pricing = article["_embedded"]["listing"]["pricing"]
            if pricing.get("currency") != "EUR":
                raise ValueError("REWE price currency is not EUR")
            discount = pricing.get("discount") or {}
            raw_end = discount.get("validTo")
            if raw_end is not None and not re.fullmatch(
                r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:CEST|CET)", raw_end
            ):
                raise ValueError("Unknown REWE offer date format")
            bonus = product.get("loyaltyBonus") or {}
            item = BrowserProduct(
                source_product_id=f"{product['id']}:{article['id']}",
                source_store_id=market_id,
                name=product["productName"],
                ean=source_ean(article),
                brand=(product.get("brand") or {}).get("name"),
                package_label=pricing.get("grammage"),
                price_cents=pricing["currentRetailPrice"],
                kind="offer" if discount else "unknown",
                # No inferred weekly start or membership eligibility.
                valid_until=raw_end[:10] if raw_end else None,
                bonus_credit_cents=bonus.get("bonusValue")
                if bonus.get("bonusType") == "CENT"
                else None,
                bonus_credit_percent=bonus.get("bonusValue")
                if bonus.get("bonusType") == "PERCENT"
                else None,
                source_url=urljoin("https://www.rewe.de", product["_links"]["detail"]["href"]),
            )
            entries.append(
                {
                    **item.model_dump(mode="json"),
                    "source": SOURCE,
                    "retailer": "REWE",
                    "store_id": market_id,
                    "postal_code": postal_code,
                    "scope": "store_channel",
                    "channel": "pickup",
                    "price_date": observed_at.astimezone(ZoneInfo("Europe/Berlin"))
                    .date()
                    .isoformat(),
                    "captured_at": observed_at.isoformat(),
                    "source_valid_to": raw_end,
                    "conditions_text": (
                        "REWE Abholpreis; Filialpreis und Angebotsbeginn nicht bestätigt."
                    ),
                }
            )
    if not entries:
        raise ValueError("REWE returned no priced articles")
    return entries, total_pages


def sync(directory, db, client, market_id, postal_code, max_pages=20, now=None):
    if not re.fullmatch(r"[0-9]+", market_id) or not re.fullmatch(r"[0-9]{5}", postal_code):
        raise ValueError("Explicit numeric market ID and five-digit postal code required")
    if not 1 <= max_pages <= 50:
        raise ValueError("max_pages must be between 1 and 50")
    now = now or datetime.now(UTC)
    directory = Path(directory) / f"{market_id}-{postal_code}"
    directory.mkdir(parents=True, exist_ok=True)
    # Separate lock/state for each market; concurrent timer/manual runs do not overlap.
    with (directory / "sync.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {"status": "locked"}
        status_path = directory / "status.json"
        previous = json.loads(status_path.read_text()) if status_path.exists() else {}
        if previous.get("next_due") and datetime.fromisoformat(previous["next_due"]) > now:
            return {**previous, "status": "cooldown"}
        result = {"source": SOURCE, "store_id": market_id, "attempted_at": now.isoformat()}
        try:
            fetcher = ConditionalFetcher(directory / "http-cache")
            entries = []
            for page in range(1, max_pages + 1):
                url = (
                    URL
                    + "?"
                    + urlencode(
                        {
                            "serviceTypes": "PICKUP",
                            "marketId": market_id,
                            "attribute": "discounted",
                            "page": page,
                        }
                    )
                )
                body, _ = fetcher.fetch(client, url)
                parsed, total_pages = parse_page(
                    json.loads(body), market_id, postal_code, now, page
                )
                if total_pages > max_pages:
                    raise ValueError("REWE page count exceeds configured limit; nothing imported")
                entries.extend(parsed)
                if page == total_pages:
                    break
            count = ObservationRepository(db).save(entries)
            db.record_run(SOURCE, "ok", count, f"Pickup observations for market {market_id}")
            result.update(status="imported", processed=count, pages=page)
        except SourceCooldown as exc:
            result.update(status="cooldown", reason=str(exc))
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            result.update(status="failed", reason=f"{type(exc).__name__}: {str(exc)[:200]}")
            db.record_run(SOURCE, "error", 0, result["reason"])
        result["next_due"] = (now + INTERVAL).isoformat()
        atomic_json(status_path, result)
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--market-id", required=True)
    parser.add_argument("--postal-code", required=True)
    parser.add_argument("--max-pages", type=int, default=20)
    parser.add_argument("--state-dir", type=Path, default=Path("data/rewe-shop"))
    args = parser.parse_args()
    db = Database(os.environ["DATABASE_URL"])
    if db.engine.dialect.name == "sqlite":
        db.initialize()
    with httpx.Client(timeout=40, follow_redirects=True) as client:
        result = sync(args.state_dir, db, client, args.market_id, args.postal_code, args.max_pages)
    print(json.dumps(result, ensure_ascii=False))
    return int(result["status"] == "failed")


if __name__ == "__main__":
    raise SystemExit(main())
