"""CLI entry point for syncing myTime expanded feeds."""

import argparse
import logging
import os
import sys
from pathlib import Path

from pricewatch_api.database import Database
from pricewatch_api.expanded_feeds import DEFAULT_INTERVAL_HOURS, MyTimeExpandedFeedSync

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("sync_expanded_feeds")


def main():
    parser = argparse.ArgumentParser(description="Sync myTime expanded feeds (listing and enrich).")
    parser.add_argument(
        "mode",
        choices=["listing", "enrich"],
        nargs="?",
        default=None,
        help="Execution mode: listing or enrich",
    )
    parser.add_argument(
        "--mode",
        dest="opt_mode",
        choices=["listing", "enrich"],
        default=None,
        help="Execution mode via flag",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=300,
        help="Maximum listing pages to scrape (default: 300)",
    )
    parser.add_argument(
        "--max-details",
        type=int,
        default=1000,
        help="Maximum product detail pages to enrich (default: 1000)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=3,
        help="Concurrency bounded requests (default: 3)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.5,
        help="Delay in seconds between requests (default: 0.5)",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Reset checkpoint progress and begin fresh cycle",
    )
    parser.add_argument(
        "--checkpoint-file",
        type=str,
        default="data/expansion/mytime-progress.json",
        help="Path to progress checkpoint file",
    )
    parser.add_argument(
        "--lock-file",
        type=str,
        default=None,
        help="Path to lock file (default: <checkpoint-file>.lock)",
    )
    parser.add_argument(
        "--interval-hours",
        type=float,
        default=DEFAULT_INTERVAL_HOURS,
        help=f"Hours before restarting completed listing cycle (default: {DEFAULT_INTERVAL_HOURS})",
    )

    args = parser.parse_args()
    mode = args.opt_mode or args.mode or "listing"

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        logger.error("DATABASE_URL environment variable is required.")
        sys.exit(1)

    db = Database(db_url)
    lock_path = Path(args.lock_file) if args.lock_file else None
    sync = MyTimeExpandedFeedSync(
        db=db,
        checkpoint_path=Path(args.checkpoint_file),
        lock_path=lock_path,
        delay=args.delay,
        workers=args.workers,
        interval_hours=args.interval_hours,
    )

    if mode == "listing":
        logger.info(
            "Starting listing sync (max_pages=%d, reset=%s, interval_hours=%.1f)...",
            args.max_pages,
            args.reset,
            args.interval_hours,
        )
        result = sync.sync_listing(
            max_pages=args.max_pages,
            reset=args.reset,
            interval_hours=args.interval_hours,
        )
        logger.info("Listing sync result: %s", result)
    elif mode == "enrich":
        logger.info(
            "Starting detail enrichment (max_details=%d, reset=%s)...", args.max_details, args.reset
        )
        result = sync.sync_enrich(max_details=args.max_details, reset=args.reset)
        logger.info("Detail enrichment result: %s", result)
    else:
        logger.error("Unknown mode: %s", mode)
        sys.exit(1)


if __name__ == "__main__":
    main()
