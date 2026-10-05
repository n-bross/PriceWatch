"""Resume bounded REWE pickup catalogue batches across public product categories."""

import argparse
import fcntl
import json
import os
import re
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode

import httpx

from .conditional_fetch import ConditionalFetcher, SourceCooldown, atomic_json
from .database import Database
from .observations import ObservationRepository
from .rewe_recurring import SOURCE, URL, parse_page

RUN_SOURCE = "rewe_shop_pickup_catalog"


def category_slugs(payload, market_id):
    search = payload["search"]
    if search.get("marketCode") != market_id or search.get("serviceTypes") != ["PICKUP"]:
        raise ValueError("Catalogue discovery did not confirm requested market and pickup")
    facets = next(f for f in payload["facets"] if f["name"] == "CATEGORY")
    slugs = list(
        dict.fromkeys(
            f["slug"]
            for f in facets["facetConstraints"]
            if "inspiration" not in f.get("categoryTags", [])
            and re.fullmatch(r"[a-z0-9-]+", f.get("slug", ""))
        )
    )
    if not slugs:
        raise ValueError("REWE returned no catalogue categories")
    return slugs


def summary(state):
    return {
        "status": state["status"],
        "cycle_articles": len(state.get("article_ids", [])),
        "pages_completed": state.get("pages_completed", 0),
        "categories": len(state.get("categories", [])),
        "categories_completed": len(state.get("completed_categories", [])),
        "next_due": state.get("next_due"),
        "reason": state.get("reason"),
    }


def sync_catalog(directory, db, client, market_id, postal_code, max_pages=40, delay=0.5, now=None):
    if not re.fullmatch(r"[0-9]+", market_id) or not re.fullmatch(r"[0-9]{5}", postal_code):
        raise ValueError("Explicit market ID and five-digit postal code required")
    if not 1 <= max_pages <= 100 or not 0 <= delay <= 60:
        raise ValueError("Batch must contain 1..100 pages and delay must be 0..60 seconds")
    now = now or datetime.now(UTC)
    directory = Path(directory) / f"{market_id}-{postal_code}"
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "catalog.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {"status": "locked"}
        path = directory / "catalog.json"
        state = json.loads(path.read_text()) if path.exists() else {}
        if state.get("next_due") and datetime.fromisoformat(state["next_due"]) > now:
            return {**summary(state), "status": "cooldown"}
        if state.get("status") == "completed":
            state = {}
        fetcher = ConditionalFetcher(directory / "catalog-http-cache")
        params = {"serviceTypes": "PICKUP", "marketId": market_id}

        def fetch(extra):
            body, _ = fetcher.fetch(client, URL + "?" + urlencode({**params, **extra}))
            return json.loads(body)

        try:
            if not state.get("categories"):
                categories = category_slugs(fetch({}), market_id)
                state = {
                    "status": "in_progress",
                    "started_at": now.isoformat(),
                    "categories": categories,
                    "pending": [{"category": c, "page": 1} for c in categories],
                    "article_ids": [],
                    "pages_completed": 0,
                    "completed_categories": [],
                    "category_totals": {},
                }
                atomic_json(path, state)
            seen = set(state["article_ids"])
            state.update(status="in_progress", next_due=None, reason=None)
            for _ in range(max_pages):
                if not state["pending"]:
                    break
                task = state["pending"][0]
                payload = fetch({"categorySlug": task["category"], "page": task["page"]})
                entries, pages = parse_page(payload, market_id, postal_code, now, task["page"])
                total = payload["pagination"]["totalResultCount"]
                if type(total) is not int or total >= 10000 or pages > 250:
                    raise ValueError("Category reaches search cap; cannot assert completeness")
                unique = []
                for entry in entries:
                    if entry["source_product_id"] not in seen:
                        unique.append(entry)
                        seen.add(entry["source_product_id"])
                # Commit this page before advancing the checkpoint. Replays are safe;
                # observations remain source-, market- and channel-specific.
                ObservationRepository(db).save(unique)
                state["pending"].pop(0)
                state["category_totals"][task["category"]] = total
                if task["page"] < pages:
                    state["pending"].append({**task, "page": task["page"] + 1})
                else:
                    state["completed_categories"].append(task["category"])
                state["article_ids"] = sorted(seen)
                state["pages_completed"] += 1
                state["updated_at"] = now.isoformat()
                atomic_json(path, state)
                if delay:
                    time.sleep(delay)
            if not state["pending"]:
                state.update(status="completed", next_due=(now + timedelta(days=1)).isoformat())
            db.record_run(RUN_SOURCE, "ok", len(seen), f"{state['status']}: market {market_id}")
        except (
            SourceCooldown,
            httpx.HTTPError,
            ValueError,
            KeyError,
            TypeError,
            AttributeError,
            StopIteration,
        ) as exc:
            state.update(
                status="cooldown" if isinstance(exc, SourceCooldown) else "failed",
                reason=f"{type(exc).__name__}: {str(exc)[:200]}",
                next_due=(now + timedelta(hours=6)).isoformat(),
            )
            db.record_run(RUN_SOURCE, "error", len(state.get("article_ids", [])), state["reason"])
        atomic_json(path, state)
        return summary(state)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--market-id", required=True)
    parser.add_argument("--postal-code", required=True)
    parser.add_argument("--max-pages", type=int, default=40)
    parser.add_argument("--delay", type=float, default=0.5)
    parser.add_argument("--state-dir", type=Path, default=Path("data/rewe-shop"))
    args = parser.parse_args()
    db = Database(os.environ["DATABASE_URL"])
    if db.engine.dialect.name == "sqlite":
        db.initialize()
    with httpx.Client(timeout=40, follow_redirects=True) as client:
        result = sync_catalog(
            args.state_dir,
            db,
            client,
            args.market_id,
            args.postal_code,
            args.max_pages,
            args.delay,
        )
    print(json.dumps({"source": SOURCE, **result}, ensure_ascii=False))
    return int(result["status"] == "failed")


if __name__ == "__main__":
    raise SystemExit(main())
