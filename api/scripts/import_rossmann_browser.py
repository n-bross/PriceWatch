"""Import timestamped public ROSSMANN evidence without inferring campaign validity."""

import argparse
import json
import os
from pathlib import Path

from pricewatch_api.database import Database
from pricewatch_api.observations import ObservationRepository
from pricewatch_api.rossmann_recurring import capture_rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path, help="JSON page capture with explicit observed_at")
    args = parser.parse_args()
    rows = capture_rows(json.loads(args.capture.read_text()))
    db = Database(os.environ["DATABASE_URL"])
    db.initialize()
    count = ObservationRepository(db).save(rows)
    print(json.dumps({"source": "rossmann_browser", "rows": count,
                      "price_date": rows[0]["price_date"]}))


if __name__ == "__main__":
    main()
