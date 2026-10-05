from .database import Database
from .flyers import FlyerRepository
from .sources import SourceError, fetch_aldi
from .web_sources import fetch_aldi_sued, fetch_kaufland, fetch_penny

AUTOMATIC = {
    "aldi_nord": "Public advertised weekly offers (ALDI Nord)",
    "aldi_sued": "Explicitly dated weekly highlights only; no expiry guesses for 'ab' offers",
    "penny": "Current public offers; regional store offers with postal_code",
    "kaufland": "Public advertised highlights, including separate Kaufland Card prices",
}
FLYER_SOURCES = {"lidl": "Current official PDF; searchable text, no verified price assignments"}


def sync_source(
    db: Database,
    source: str,
    postal_code: str | None = None,
    radius_km: int = 30,
    max_stores: int = 3,
):
    status_key = f"{source}:area:{postal_code}" if source == "penny" and postal_code else source
    try:
        if source in FLYER_SOURCES:
            import os

            from .flyer_sources import fetch_lidl_flyer

            info, content = fetch_lidl_flyer()
            repo = FlyerRepository(db, os.getenv("PRICEWATCH_FLYER_DIR", "./data/flyers"))
            result = repo.import_pdf(info, content)
            db.record_run(source, "ok", result["pages"])
            return {
                "source": source,
                "processed": 0,
                "postal_code": None,
                "stores": 0,
                "flyer": result,
            }
        if source == "penny":
            groups, stores = fetch_penny(postal_code, radius_km, max_stores)
        else:
            fetcher = {
                "aldi_nord": fetch_aldi,
                "aldi_sued": fetch_aldi_sued,
                "kaufland": fetch_kaufland,
            }.get(source)
            if fetcher is None:
                raise SourceError("Source has no automatic adapter")
            groups, stores = {source: fetcher()}, []
        count = 0
        for key, items in groups.items():
            count += db.import_prices(key, items, snapshot=True)
        if source == "penny" and postal_code:
            db.save_area_stores(postal_code, "penny", stores)
        db.record_run(status_key, "ok", count)
        return {
            "source": source,
            "processed": count,
            "postal_code": postal_code,
            "stores": len(stores),
        }
    except SourceError as exc:
        db.record_run(status_key, "error", 0, str(exc))
        raise
    except (ValueError, KeyError, TypeError) as exc:
        error = SourceError(f"{source}: invalid or changed source data format")
        db.record_run(status_key, "error", 0, str(error))
        raise error from exc
