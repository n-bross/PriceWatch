"""Import a dated browser capture; replay never substitutes the import time."""

import argparse
import json
import os
from datetime import datetime
from pathlib import Path

from pricewatch_api.database import Database
from pricewatch_api.edeka_offers import parse_capture
from pricewatch_api.observations import ObservationRepository


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "capture", nargs="?", type=Path, default=Path("data/retailer-audit/edeka-browser.json")
    )
    parser.add_argument("--observed-at", help="Actual capture timestamp, including timezone")
    args = parser.parse_args()
    data = json.loads(args.capture.read_text())
    timestamp = args.observed_at or data.get("observed_at")
    if not timestamp:
        parser.error("Capture needs observed_at or --observed-at; import time is not evidence")
    prices, records = parse_capture(data, datetime.fromisoformat(timestamp))
    db = Database(os.environ["DATABASE_URL"])
    for record in records:
        record["source"] = "edeka_browser"
    count = db.import_prices("edeka_browser", prices)
    print("published", count, "observations", ObservationRepository(db).save(records))
    db.record_run("edeka_browser", "ok", count, "Timestamped public browser capture")


if __name__ == "__main__":
    main()
