import argparse
import os
import re
from pathlib import Path

from .catalog import ProductRepository
from .database import Database
from .ingestion import AUTOMATIC, FLYER_SOURCES, sync_source
from .observations import sync_external
from .sources import SourceError
from .tracker import Tracker


def main():
    parser = argparse.ArgumentParser(description="PriceWatch price ingestion")
    parser.add_argument(
        "command",
        choices=[
            "sync-aldi",
            "sync",
            "track",
            "catalog-sync",
            "catalog-import-dataset",
            "external-sync",
        ],
    )
    parser.add_argument("--file", type=Path)
    parser.add_argument(
        "--external-source",
        default="all",
        choices=["all", "dataset", "dm", "rewe", "open_prices", "marktguru"],
    )
    parser.add_argument("--source", choices=[*AUTOMATIC, *FLYER_SOURCES, "all"], default="all")
    parser.add_argument("--postal-code")
    parser.add_argument("--radius-km", type=int, default=30)
    parser.add_argument("--max-stores", type=int, default=3)
    args = parser.parse_args()
    if args.postal_code and not re.fullmatch(r"\d{5}", args.postal_code):
        parser.error("--postal-code must contain five digits")
    if not 1 <= args.radius_km <= 100 or not 1 <= args.max_stores <= 20:
        parser.error("radius must be 1..100 km and max-stores 1..20")
    db = Database(os.getenv("DATABASE_URL", "sqlite:///./pricewatch.db"))
    if db.engine.dialect.name == "sqlite":
        db.initialize()
    try:
        if args.command == "external-sync":
            import json

            print(json.dumps(sync_external(db, Path("./data/catalog"), args.external_source)))
            return
        if args.command == "catalog-import-dataset":
            import json

            if not args.file:
                parser.error("catalog-import-dataset requires --file")
            print(json.dumps(ProductRepository(db).import_dataset_products(args.file)))
            return
        if args.command == "catalog-sync":
            import json

            directory = Path(os.getenv("PRICEWATCH_CATALOG_DIR", "./data/catalog"))
            try:
                print(json.dumps(ProductRepository(db).sync_off(directory)))
            except SourceError as exc:
                parser.exit(1, str(exc) + "\n")
            return
        if args.command == "track":
            import json

            print(json.dumps(Tracker(db).run(), default=str))
            return
        sources = (
            ["aldi_nord"]
            if args.command == "sync-aldi"
            else ([*AUTOMATIC, *FLYER_SOURCES] if args.source == "all" else [args.source])
        )
        failed = False
        for source in sources:
            try:
                result = sync_source(db, source, args.postal_code, args.radius_km, args.max_stores)
            except SourceError as exc:
                print(f"{source}: {exc}")
                failed = True
                continue
            if "flyer" in result:
                print(f"{source}: {result['flyer']['pages']} searchable flyer pages")
            else:
                print(f"{source}: {result['processed']} prices, {result['stores']} stores")
        if failed:
            parser.exit(1)
    finally:
        db.engine.dispose()


if __name__ == "__main__":
    main()
