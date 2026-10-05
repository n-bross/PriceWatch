"""Read-only import evidence: observed dates and bounded checkpoint summaries.

A checkpoint is not evidence that a scheduler is enabled or a process is running.
Never expose raw checkpoint errors, URLs, cached bodies or credentials here.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select

from .observations import observations

JOBS = (
    ("globus", "GLOBUS Sortiment", ("globus_website",), "expansion/globus-bulk.json", "bulk"),
    ("combi", "Combi Sortiment", ("combi_website",), "expansion/combi-bulk.json", "bulk"),
    ("mytime", "myTime", ("mytime_website",), "expansion/mytime-progress.json", "mytime"),
    (
        "recovered",
        "Denns, BIO COMPANY, Alnatura, Netto mit Hund",
        ("denns_website", "bio_company_website", "alnatura_website", "netto_dog_website"),
        "expansion/recovered-sources-status.json",
        "recovered",
    ),
    ("edeka", "EDEKA Direktabruf", ("edeka_public_offers",), "edeka-offers/status.json", "single"),
    ("rossmann", "ROSSMANN", ("rossmann_browser",), "rossmann-recurring/state.json", "single"),
    ("rewe", "REWE Browserimport", ("rewe_browser",), None, "manual"),
    ("rewe_shop", "REWE Abholsortiment", ("rewe_shop_pickup",), None, "rewe_catalog"),
    ("edeka_browser", "EDEKA Browserimport", ("edeka_browser",), None, "manual"),
)


def utc_timestamp(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return datetime.fromtimestamp(value, UTC).isoformat()
        except (ValueError, OverflowError, OSError):
            pass
    return None


def summarize(path, kind, now):
    result = {"status": "manual" if kind == "manual" else "unknown"}
    if path is None or not path.exists():
        return result
    try:
        state = json.loads(path.read_text())
        result["checkpoint_at"] = datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat()
        if kind == "bulk":
            result.update(
                pages_completed=len(state.get("completed", [])),
                pages_pending=len(state.get("pending", [])),
                cycle_products=len(state.get("products", [])),
                error_count=len(state.get("errors", {})),
            )
            result["status"] = (
                "completed_with_errors"
                if state.get("complete") and result["error_count"]
                else "completed"
                if state.get("complete")
                else "in_progress"
            )
            result["cycle_completed_at"] = utc_timestamp(state.get("completed_at_epoch"))
            retry = state.get("retry_after_epoch", 0)
        elif kind == "mytime":
            total = state.get("total_pages")
            result.update(
                pages_completed=max(0, state.get("next_page", 1) - 1),
                pages_total=total,
                cycle_products=len(state.get("product_url_map", {})),
                verified_barcodes=len(state.get("verified_gtins", {})),
            )
            result["status"] = (
                "listing_completed"
                if total and result["pages_completed"] >= total
                else "in_progress"
            )
            result["cycle_completed_at"] = utc_timestamp(state.get("listing_completed_at"))
            retry = state.get("cooldown_until") or 0
        elif kind == "rewe_catalog":
            status = state.get("status", "unknown")
            if not isinstance(state.get("pages_completed", 0), int):
                raise ValueError("Invalid REWE page count")
            result.update(
                status=status
                if status in {"in_progress", "completed", "failed", "cooldown"}
                else "unknown",
                pages_completed=state.get("pages_completed", 0),
                cycle_products=len(state.get("article_ids", [])),
                categories_total=len(state.get("categories", [])),
                categories_completed=len(state.get("completed_categories", [])),
            )
            retry = (
                datetime.fromisoformat(state["next_due"]).timestamp()
                if state.get("next_due")
                else 0
            )
        elif kind == "recovered":
            if not isinstance(state, list):
                raise ValueError("Invalid recovered-source checkpoint")
            result["checked_pages"] = len(state)
            result["error_count"] = sum(x.get("status") == "failed" for x in state)
            result["status"] = (
                "failed" if result["error_count"] else "checked" if state else "unknown"
            )
            retry = 0
        else:
            if isinstance(state.get("pages"), list):
                result["pages_completed"] = len(state["pages"])
            if state.get("last_success"):
                result["last_success_at"] = utc_timestamp(state["last_success"])
            status = state.get("status", "unknown")
            result["status"] = (
                status
                if status
                in {"blocked", "failed", "cooldown", "imported", "complete", "running", "locked"}
                else "unknown"
            )
            # A saved "running" status means an incomplete capture, not a live process.
            if result["status"] == "running":
                result["status"] = "in_progress"
            if result["status"] == "complete":
                result["status"] = "completed"
            retry = state.get("next_due", 0)
        if isinstance(retry, (int, float)) and retry > now.timestamp():
            result["retry_at"] = utc_timestamp(retry)
            if result["status"] not in {"blocked", "failed", "completed"}:
                result["status"] = "cooldown"
        return result
    except (OSError, ValueError, TypeError, AttributeError):
        return {"status": "unreadable"}


def import_status(db, data_dir, now=None):
    now = now or datetime.now(UTC)
    with db.engine.connect() as conn:
        stats = {
            row.source: dict(row._mapping)
            for row in conn.execute(
                select(
                    observations.c.source,
                    func.count().label("observations"),
                    func.max(observations.c.price_date).label("latest_price_date"),
                )
                .where(
                    observations.c.source.in_(
                        sorted({source for _, _, sources, _, _ in JOBS for source in sources})
                    )
                )
                .group_by(observations.c.source)
            )
        }
    items = []
    for identifier, name, sources, relative, kind in JOBS:
        dates = [
            stats[s]["latest_price_date"]
            for s in sources
            if s in stats and stats[s]["latest_price_date"]
        ]
        evidence = summarize(Path(data_dir) / relative if relative else None, kind, now)
        if kind == "rewe_catalog":
            checkpoints = sorted(Path(data_dir).glob("rewe-shop/*/catalog.json"))
            summaries = [summarize(path, kind, now) for path in checkpoints]
            if summaries:
                statuses = {s["status"] for s in summaries}
                evidence = {
                    "markets": len(summaries),
                    "status": next(
                        (
                            s
                            for s in [
                                "failed",
                                "unreadable",
                                "in_progress",
                                "cooldown",
                                "unknown",
                                "completed",
                            ]
                            if s in statuses
                        ),
                        "unknown",
                    ),
                    **{
                        key: sum(s.get(key, 0) for s in summaries)
                        for key in [
                            "pages_completed",
                            "cycle_products",
                            "categories_total",
                            "categories_completed",
                        ]
                    },
                }
        items.append(
            {
                "id": identifier,
                "name": name,
                "observations": sum(stats.get(s, {}).get("observations", 0) for s in sources),
                "latest_price_date": max(dates) if dates else None,
                **evidence,
            }
        )
    return {
        "checked_at": now.isoformat(),
        "items": items,
        "note": "Beobachtungen enthalten Historie und regionale Varianten, nicht nur aktuelle "
        "oder unterschiedliche Produkte. Ein abgeschlossener Durchlauf bestätigt keine "
        "vollständige Händlerabdeckung. Der Importstand zeigt keinen laufenden Prozess an.",
    }
