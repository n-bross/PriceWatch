"""One conditional HTTP request per run; safe for an unattended six-hour timer."""

import argparse
import fcntl
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

from pricewatch_api.conditional_fetch import ConditionalFetcher, SourceCooldown, atomic_json
from pricewatch_api.database import Database
from pricewatch_api.edeka_offers import URL, parse_html
from pricewatch_api.observations import ObservationRepository


def sync(directory, db, client):
    result = {"source": "edeka_public_offers", "attempted_at": datetime.now(UTC).isoformat()}
    try:
        body, status = ConditionalFetcher(directory / "http-cache").fetch(client, URL)
        prices, records = parse_html(body, datetime.now(UTC))
        count = db.import_prices("edeka_public_offers", prices)
        ObservationRepository(db).save(records)
        db.record_run("edeka_public_offers", "ok", count, "Explicit dated public offer dialogs")
        today = datetime.now(ZoneInfo("Europe/Berlin")).date()
        result.update(
            status="imported",
            http_status=status,
            parsed=count,
            current=sum(p.valid_from <= today <= p.valid_until for p in prices),
            upcoming=sum(p.valid_from > today for p in prices),
            expired=sum(p.valid_until < today for p in prices),
        )
    except SourceCooldown as exc:
        result.update(status="cooldown", reason=str(exc))
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        result.update(status="failed", reason=f"{type(exc).__name__}: {str(exc)[:200]}")
        db.record_run("edeka_public_offers", "error", 0, result["reason"])
    atomic_json(directory / "status.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, default=Path("data/edeka-offers"))
    args = parser.parse_args()
    args.state_dir.mkdir(parents=True, exist_ok=True)
    with (args.state_dir / "sync.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('{"status":"locked"}')
            return 0
        db = Database(os.environ["DATABASE_URL"])
        with httpx.Client(
            timeout=40,
            follow_redirects=True,
            headers={"User-Agent": "PriceWatch/0.1 (public price catalog)"},
        ) as client:
            result = sync(args.state_dir, db, client)
        print(json.dumps(result, ensure_ascii=False))
        return int(result["status"] == "failed")


if __name__ == "__main__":
    raise SystemExit(main())
