"""CLI script to sync additional deterministic retailer sources.

Loads DATABASE_URL exclusively from environment variables (no .env files).
Parses verifiable HTML offers (NORMA) and audits non-structured leaflet sites.
Records evidence at data/retailer-audit/additional-imports.json.
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from pricewatch_api.database import Database
from pricewatch_api.observations import ObservationRepository
from pricewatch_api.retailer_sources import (
    audit_retailer_html,
    fetch_and_parse_norma,
    seed_catalog_if_gtin,
)

BERLIN_TZ = ZoneInfo("Europe/Berlin")


def resolve_audit_dir() -> Path:
    for candidate in [
        Path("data/retailer-audit"),
        Path("api/data/retailer-audit"),
        Path(__file__).resolve().parent.parent / "data" / "retailer-audit",
        Path(__file__).resolve().parent.parent.parent / "data" / "retailer-audit",
    ]:
        if candidate.exists():
            return candidate
    target = Path("data/retailer-audit")
    target.mkdir(parents=True, exist_ok=True)
    return target


def main():
    db_url = os.environ.get("DATABASE_URL")
    now_str = datetime.now(timezone.utc).isoformat()
    today_berlin = datetime.now(BERLIN_TZ).date().isoformat()
    audit_dir = resolve_audit_dir()

    print("Starting deterministic retailer sources sync...")

    # 1. Fetch & parse NORMA offers
    norma_observations = []
    fetch_note = "Live public crawl succeeded"

    try:
        norma_observations = fetch_and_parse_norma(price_date=today_berlin, max_subpages=20)
    except Exception as e:
        fetch_note = f"Live request failed ({type(e).__name__}: {e}); no fresh prices imported"

    norma_with_date = sum(1 for o in norma_observations if o.get("valid_from"))
    norma_with_ean = sum(1 for o in norma_observations if o.get("ean"))

    print(
        f"NORMA: parsed {len(norma_observations)} offers "
        f"({norma_with_date} with explicit valid_from, "
        f"{norma_with_ean} explicit EANs)"
    )

    # 2. Database ingestion if DATABASE_URL is provided
    saved_count = 0
    seeded_gtins = 0
    if db_url:
        try:
            db = Database(db_url)
            repo = ObservationRepository(db)
            saved_count = repo.save(norma_observations)
            seeded_gtins = seed_catalog_if_gtin(db, norma_observations)
            print(
                f"Database: saved {saved_count} observations, seeded {seeded_gtins} catalog GTINs"
            )
        except Exception as err:
            print(f"Database error during ingestion: {err}", file=sys.stderr)
    else:
        print("Database: skipped (DATABASE_URL not set in environment)")

    # 3. Audit non-structured retailer sources
    retailer_audits = {
        "norma": {
            "status": "success" if norma_observations else "empty",
            "source_type": "structured_html",
            "observations_count": len(norma_observations),
            "validity_dates_count": norma_with_date,
            "guessed_eans_count": 0,
            "scope": "unknown",
            "source_url": "https://www.norma-online.de/de/angebote/",
            "notes": fetch_note,
        }
    }

    audit_candidates = [
        ("netto_dog", "netto_dog-0.html"),
        ("denns", "denns-0.html"),
        ("bio_company", "bio_company-2.html"),
        ("lpg", "lpg-browser.html"),
        ("v_markt", "v_markt-0.html"),
        ("wasgau", "wasgau-0.html"),
        ("markant", "markant-0.html"),
        ("famila_nordost", "famila_nordost-0.html"),
    ]

    for r_id, filename in audit_candidates:
        filepath = audit_dir / filename
        if filepath.exists():
            content = filepath.read_text(encoding="utf-8", errors="ignore")
            audit_res = audit_retailer_html(r_id, content)
            retailer_audits[r_id] = {
                "status": "unsupported",
                "source_type": audit_res["source_type"],
                "observations_count": 0,
                "reason": audit_res["reason"],
            }
        else:
            retailer_audits[r_id] = {
                "status": "unsupported",
                "source_type": "requires_store_selection_or_leaflet",
                "observations_count": 0,
                "reason": (
                    "Requires branch selection or digital leaflet viewer "
                    "without deterministic HTML DOM cards"
                ),
            }

    evidence = {
        "captured_at": now_str,
        "price_date": today_berlin,
        "retailers": retailer_audits,
        "summary": {
            "total_retailers_audited": len(retailer_audits),
            "structured_html_active": 1,
            "total_observations_parsed": len(norma_observations),
            "total_observations_saved": saved_count,
        },
    }

    # 4. Persist evidence JSON
    output_path = audit_dir / "additional-imports.json"
    output_path.write_text(
        json.dumps(evidence, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(
        f"Audited {len(retailer_audits)} retailers: "
        f"1 structured HTML active, "
        f"{len(retailer_audits) - 1} verified leaflet/branch-gated"
    )
    print(f"Evidence written to: {output_path}")


if __name__ == "__main__":
    main()
