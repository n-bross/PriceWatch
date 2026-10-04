import os
import secrets
from contextlib import asynccontextmanager
from datetime import date, datetime
from pathlib import Path as FilePath
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    File,
    Header,
    HTTPException,
    Path,
    Query,
    UploadFile,
)
from fastapi.responses import FileResponse
from pydantic import HttpUrl, ValidationError
from starlette.concurrency import run_in_threadpool

from .barcodes import barcode_scope
from .catalog import (
    ArticleIdentity,
    ProductBatch,
    ProductRepository,
    articles,
    product_sources,
    products,
)
from .comparison import register_comparison_routes
from .database import Database
from .flyers import MAX_PDF_BYTES, FlyerInfo, FlyerRepository
from .import_status import import_status
from .ingestion import AUTOMATIC, FLYER_SOURCES, sync_source
from .models import RETAILERS, ImportBatch, PricePage, Retailer
from .observations import ObservationRepository, observations
from .receipts import MAX_RECEIPT_BYTES, ReceiptRepository, ReceiptReview, receipts
from .rewe_browser import ReweBrowserBatch, import_browser_prices
from .sources import SourceError, fetch_aldi
from .tracker import Tracker, refresh_requests, watches


def create_app(database_url: str | None = None, ingest_key: str | None = None) -> FastAPI:
    db = Database(database_url or os.getenv("DATABASE_URL", "sqlite:///./pricewatch.db"))
    key = ingest_key if ingest_key is not None else os.getenv("PRICEWATCH_INGEST_KEY", "")

    @asynccontextmanager
    async def lifespan(app):
        # Production PostgreSQL/Supabase schema is managed by migrations.
        if db.engine.dialect.name == "sqlite":
            db.initialize()
        yield
        db.engine.dispose()

    app = FastAPI(
        title="PriceWatch API",
        version="0.1.0",
        lifespan=lifespan,
        description="Real price observations and offers. Money is in EUR cents. "
        "Chain advertisements do not guarantee branch availability.",
    )
    app.state.db = db
    register_comparison_routes(app, db)

    @app.get("/", include_in_schema=False)
    @app.get("/compare", include_in_schema=False)
    def comparison_website():
        return FileResponse(FilePath(__file__).with_name("compare.html"))

    product_repo = ProductRepository(db)
    observation_repo = ObservationRepository(db)
    flyer_repo = FlyerRepository(db, os.getenv("PRICEWATCH_FLYER_DIR", "./data/flyers"))
    receipt_repo = ReceiptRepository(db, os.getenv("PRICEWATCH_RECEIPT_DIR", "./data/receipts"))
    tracker = Tracker(db)

    def authorize(authorization: Annotated[str | None, Header()] = None):
        if not key:
            raise HTTPException(503, "Imports disabled: configure PRICEWATCH_INGEST_KEY")
        if not secrets.compare_digest((authorization or "").encode(), f"Bearer {key}".encode()):
            raise HTTPException(
                401, "Invalid ingestion token", headers={"WWW-Authenticate": "Bearer"}
            )

    @app.get("/health")
    def health():
        from sqlalchemy import select

        from .database import area_stores, prices, runs, versions
        from .flyers import flyers, pages

        with db.engine.connect() as conn:
            conn.execute(select(prices.c.id).limit(1))
            conn.execute(select(runs.c.source).limit(1))
            conn.execute(select(area_stores).limit(1))
            conn.execute(select(flyers.c.id).limit(1))
            conn.execute(select(pages.c.flyer_id).limit(1))
            for table in [
                versions,
                receipts,
                watches,
                refresh_requests,
                products,
                articles,
                product_sources,
                observations,
            ]:
                conn.execute(select(table).limit(1))
        return {"status": "ok"}

    @app.get("/products", include_in_schema=False)
    def product_tool():
        return FileResponse(FilePath(__file__).with_name("product_tool.html"))

    @app.get("/rewe-import", include_in_schema=False)
    def rewe_import_tool():
        return FileResponse(FilePath(__file__).with_name("rewe_import.html"))

    @app.get("/rewe-export.js", include_in_schema=False)
    def rewe_export_script():
        return FileResponse(
            FilePath(__file__).with_name("rewe_export.js"), media_type="application/javascript"
        )

    @app.get("/v1/import-status")
    def current_import_status():
        return import_status(db, os.getenv("PRICEWATCH_DATA_DIR", "./data"))

    @app.get("/v1/products/status")
    def product_status():
        return {**product_repo.status(), "price_observations": observation_repo.status()}

    @app.get("/v1/price-observations/status")
    def observation_status():
        return observation_repo.status()

    @app.post("/v1/rewe/browser-prices", dependencies=[Depends(authorize)])
    def rewe_browser_import(batch: ReweBrowserBatch):
        return import_browser_prices(db, batch)

    @app.get("/v1/price-observations")
    def observation_list(
        q: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
        ean: Annotated[str | None, Query(pattern=r"^(\d{8}|\d{13}|\d{14})$")] = None,
        retailer: Annotated[str | None, Query(min_length=1, max_length=300)] = None,
        source: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
        postal_code: Annotated[str | None, Query(pattern=r"^\d{5}$")] = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        offset: Annotated[int, Query(ge=0, le=1000000)] = 0,
    ):
        if ean and barcode_scope(ean) == "restricted_circulation" and not retailer:
            raise HTTPException(422, "Local barcode requires retailer context")
        return observation_repo.query(q, ean, retailer, source, postal_code, limit, offset)

    @app.get("/v1/products")
    def product_list(
        q: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
        ean: Annotated[str | None, Query(pattern=r"^(\d{8}|\d{13}|\d{14})$")] = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        offset: Annotated[int, Query(ge=0, le=1000000)] = 0,
        category: Annotated[str | None, Query(min_length=1, max_length=300)] = None,
        brand: Annotated[str | None, Query(min_length=1, max_length=300)] = None,
    ):
        return product_repo.query(q, ean, limit, offset, category, brand)

    @app.get("/v1/products/{ean}")
    def product_detail(ean: str):
        product = product_repo.detail(ean)
        if product is None:
            raise HTTPException(404, "Unknown product barcode")
        product["price_observations"] = (
            observation_repo.query(ean=ean, limit=100)
            if barcode_scope(ean) != "restricted_circulation"
            else {"items": [], "total": 0, "note": "Local barcode requires retailer context"}
        )
        return product

    @app.post("/v1/products/import", dependencies=[Depends(authorize)])
    def product_import(batch: ProductBatch):
        return {"processed": product_repo.upsert(batch.products)}

    @app.put("/v1/retailer-products", dependencies=[Depends(authorize)])
    def article_identity(item: ArticleIdentity):
        try:
            product_repo.link(item)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"status": "saved"}

    @app.delete("/v1/retailer-products", dependencies=[Depends(authorize)])
    def delete_article_identity(
        retailer: Retailer, source_product_id: str, store_id: str | None = None
    ):
        return {"deleted": product_repo.unlink(retailer, source_product_id, store_id)}

    @app.get("/v1/retailers")
    def retailers():
        today = datetime.now(ZoneInfo("Europe/Berlin")).date()
        counts = db.catalog_counts(today)
        flyer_counts = flyer_repo.counts(today)
        return {
            "items": [
                {
                    "id": k,
                    "name": v,
                    **counts.get(k, {"price_count": 0, "offer_count": 0}),
                    "flyer_page_count": flyer_counts.get(k, 0),
                    "mode": "automatic"
                    if k in AUTOMATIC
                    else ("flyer_search" if k in FLYER_SOURCES else "import_only"),
                }
                for k, v in RETAILERS.items()
            ],
            "note": "Counts cover stored currently valid data, exclude membership prices, "
            "and may contain several stores; not a complete retailer assortment",
        }

    @app.get("/v1/sources")
    def sources():
        runs = db.source_runs()
        return {
            "items": [
                *[
                    {
                        "id": source,
                        "retailer": source,
                        "mode": "automatic",
                        "coverage": coverage,
                        "run": runs.pop(source, None),
                    }
                    for source, coverage in AUTOMATIC.items()
                ],
                *[
                    {
                        "id": r,
                        "retailer": r,
                        "mode": "import_only",
                        "coverage": "Requires a feed/import; no automatic retrieval",
                    }
                    for r in RETAILERS
                    if r not in AUTOMATIC and r not in FLYER_SOURCES
                ],
                *[
                    {
                        "id": source,
                        "retailer": source,
                        "mode": "flyer_search",
                        "coverage": coverage,
                        "run": runs.pop(source, None),
                    }
                    for source, coverage in FLYER_SOURCES.items()
                ],
                *[
                    {
                        "id": source,
                        "mode": "automatic"
                        if source.split(":")[0] in AUTOMATIC
                        else (
                            "flyer_search" if source.split(":")[0] in FLYER_SOURCES else "import"
                        ),
                        "run": run,
                    }
                    for source, run in runs.items()
                ],
            ]
        }

    def list_prices(
        q: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
        retailer: Retailer | None = None,
        on: date | None = None,
        postal_code: Annotated[str | None, Query(pattern=r"^\d{5}$")] = None,
        store_id: Annotated[str | None, Query(min_length=1, max_length=300)] = None,
        ean: Annotated[str | None, Query(pattern=r"^(\d{8}|\d{13}|\d{14})$")] = None,
        include_membership: bool = False,
        max_age_days: Annotated[int, Query(ge=1, le=365)] = 7,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        offset: Annotated[int, Query(ge=0, le=100000)] = 0,
    ):
        return dict(
            q=q,
            retailer=retailer,
            on=on or datetime.now(ZoneInfo("Europe/Berlin")).date(),
            postal_code=postal_code,
            store_id=store_id,
            ean=ean,
            include_membership=include_membership,
            max_age_days=max_age_days,
            limit=limit,
            offset=offset,
        )

    @app.get("/v1/prices", response_model=PricePage)
    def prices(filters: Annotated[dict, Depends(list_prices)]):
        require_barcode_context(filters)
        return db.query(**filters, kind=None)

    @app.get("/v1/offers", response_model=PricePage)
    def offers(filters: Annotated[dict, Depends(list_prices)]):
        require_barcode_context(filters)
        return db.query(**filters, kind="offer")

    def require_barcode_context(filters):
        if filters["ean"] and barcode_scope(filters["ean"]) == "restricted_circulation":
            if not filters["retailer"]:
                raise HTTPException(422, "Restricted-circulation barcode requires retailer context")

    @app.get("/v1/products/{barcode}/prices", response_model=PricePage)
    def product_prices(
        barcode: str,
        filters: Annotated[dict, Depends(list_prices)],
        kind: Literal["regular", "offer"] | None = None,
    ):
        if product_repo.detail(barcode) is None:
            raise HTTPException(404, "Unknown product barcode")
        filters["ean"] = barcode
        require_barcode_context(filters)
        result = db.query(**filters, kind=kind)
        result.price_observations = observation_repo.query(
            ean=barcode,
            retailer=RETAILERS.get(filters["retailer"]) if filters["retailer"] else None,
            postal_code=filters["postal_code"],
            limit=filters["limit"],
            offset=filters["offset"],
        )
        return result

    @app.post("/v1/imports", dependencies=[Depends(authorize)])
    def import_prices(batch: ImportBatch):
        if batch.source in AUTOMATIC or batch.source in FLYER_SOURCES:
            raise HTTPException(422, "Source name is reserved for an automatic source")
        count = db.import_prices(batch.source, batch.prices)
        db.record_run(batch.source, "ok", count)
        return {"source": batch.source, "processed": count}

    @app.post("/v1/sources/aldi_nord/sync", dependencies=[Depends(authorize)])
    def sync_aldi():
        try:
            items = fetch_aldi()
            count = db.import_prices("aldi_nord", items, snapshot=True)
        except SourceError as exc:
            db.record_run("aldi_nord", "error", 0, str(exc))
            raise HTTPException(502, str(exc)) from exc
        db.record_run("aldi_nord", "ok", count)
        return {"source": "aldi_nord", "processed": count}

    @app.post("/v1/sources/{source}/sync", dependencies=[Depends(authorize)])
    def sync_other_source(
        source: Retailer,
        postal_code: Annotated[str | None, Query(pattern=r"^\d{5}$")] = None,
        radius_km: Annotated[int, Query(ge=1, le=100)] = 30,
        max_stores: Annotated[int, Query(ge=1, le=20)] = 3,
    ):
        if source not in AUTOMATIC and source not in FLYER_SOURCES:
            raise HTTPException(
                422, "No automatic adapter yet; use a verified feed or flyer import"
            )
        try:
            return sync_source(db, source, postal_code, radius_km, max_stores)
        except SourceError as exc:
            raise HTTPException(502, str(exc)) from exc

    @app.get("/v1/areas/{postal_code}/stores")
    def area_stores(postal_code: Annotated[str, Path(pattern=r"^\d{5}$")]):
        return {
            "items": db.stores_for_area(postal_code),
            "note": "Imported store candidates; distances are straight-line from PLZ center",
        }

    @app.post("/v1/flyers/import", dependencies=[Depends(authorize)])
    async def import_flyer(
        file: Annotated[UploadFile, File(description="Official offer PDF, max 80 MiB")],
        title: Annotated[str, Query(min_length=1, max_length=300)],
        retailer: Retailer,
        source_url: HttpUrl,
        valid_from: date,
        valid_until: date,
        scope: str = "chain_advertised",
        postal_code: Annotated[str | None, Query(pattern=r"^\d{5}$")] = None,
        store_id: str | None = None,
        region_label: str | None = None,
    ):
        try:
            info = FlyerInfo(
                title=title,
                retailer=retailer,
                source_url=source_url,
                valid_from=valid_from,
                valid_until=valid_until,
                scope=scope,
                postal_code=postal_code,
                store_id=store_id,
                region_label=region_label,
            )
        except ValidationError as exc:
            raise HTTPException(422, "Invalid flyer metadata") from exc
        content = bytearray()
        try:
            while chunk := await file.read(1024 * 1024):
                content.extend(chunk)
                if len(content) > MAX_PDF_BYTES:
                    raise HTTPException(413, "PDF exceeds 80 MiB")
        finally:
            await file.close()
        try:
            return await run_in_threadpool(flyer_repo.import_pdf, info, bytes(content))
        except SourceError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/v1/flyers")
    def search_flyers(
        q: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
        retailer: Retailer | None = None,
        on: date | None = None,
        postal_code: Annotated[str | None, Query(pattern=r"^\d{5}$")] = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
        offset: Annotated[int, Query(ge=0)] = 0,
    ):
        return flyer_repo.search(
            q=q,
            retailer=retailer,
            on=on or datetime.now(ZoneInfo("Europe/Berlin")).date(),
            postal_code=postal_code,
            limit=limit,
            offset=offset,
        )

    @app.get("/v1/flyers/{flyer_id}/pdf")
    def download_flyer(flyer_id: Annotated[str, Path(pattern=r"^[a-f0-9]{64}$")]):
        path = flyer_repo.pdf_path(flyer_id)
        if not path.is_file():
            raise HTTPException(404, "Flyer PDF unavailable")
        return FileResponse(path, media_type="application/pdf", filename=f"{flyer_id}.pdf")

    @app.get("/tools", include_in_schema=False)
    def receipt_tool():
        return FileResponse(
            FilePath(__file__).with_name("receipt_tool.html"), media_type="text/html"
        )

    @app.get("/v1/prices/{price_id}/history")
    def price_history(price_id: str):
        return {
            "items": db.price_history(price_id),
            "note": "Observation history since tracking began; "
            "source validity dates are distinct from observation times",
        }

    @app.get("/v1/tracker")
    def tracker_status():
        return {
            "items": tracker.state(),
            "interval_minutes": 15,
            "note": "Automatic sources import verified structured fields; "
            "watch_only sources detect page changes without importing prices",
        }

    @app.get("/v1/tracker/changes")
    def tracker_changes(limit: Annotated[int, Query(ge=1, le=100)] = 30):
        return {"items": tracker.changes(limit)}

    @app.post("/v1/tracker/run", status_code=202, dependencies=[Depends(authorize)])
    def run_tracker(background: BackgroundTasks):
        background.add_task(tracker.run)
        return {"status": "scheduled"}

    @app.post("/v1/receipts", dependencies=[Depends(authorize)])
    async def upload_receipt(
        file: Annotated[UploadFile, File(description="Kassenbon as PDF, PNG or JPEG, max 20 MiB")],
        retailer: Retailer | None = None,
        purchase_date: date | None = None,
        postal_code: Annotated[str | None, Query(pattern=r"^\d{5}$")] = None,
        store_id: Annotated[str | None, Query(min_length=1, max_length=300)] = None,
    ):
        content = bytearray()
        try:
            while chunk := await file.read(1024 * 1024):
                content.extend(chunk)
                if len(content) > MAX_RECEIPT_BYTES:
                    raise HTTPException(413, "Receipt exceeds 20 MiB")
        finally:
            await file.close()
        try:
            return await run_in_threadpool(
                receipt_repo.upload,
                bytes(content),
                {
                    "retailer": retailer,
                    "purchase_date": purchase_date,
                    "postal_code": postal_code,
                    "store_id": store_id,
                },
            )
        except (SourceError, ValidationError) as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/v1/receipts", dependencies=[Depends(authorize)])
    def list_receipts(
        limit: Annotated[int, Query(ge=1, le=100)] = 20, offset: Annotated[int, Query(ge=0)] = 0
    ):
        return {"items": receipt_repo.list(limit, offset)}

    @app.get("/v1/receipts/{receipt_id}", dependencies=[Depends(authorize)])
    def get_receipt(receipt_id: str):
        from sqlalchemy import select

        try:
            result = receipt_repo.get(receipt_id)
        except KeyError as exc:
            raise HTTPException(404, "Receipt not found") from exc
        with db.engine.connect() as conn:
            request = (
                conn.execute(
                    select(refresh_requests).where(refresh_requests.c.receipt_id == receipt_id)
                )
                .mappings()
                .first()
            )
        result["recheck"] = dict(request) if request else None
        return result

    @app.put("/v1/receipts/{receipt_id}/review", dependencies=[Depends(authorize)])
    def review_receipt(receipt_id: str, review: ReceiptReview):
        try:
            receipt_repo.review(receipt_id, review)
            return get_receipt(receipt_id)
        except KeyError as exc:
            raise HTTPException(404, "Receipt not found") from exc

    @app.delete("/v1/receipts/{receipt_id}", dependencies=[Depends(authorize)])
    def delete_receipt(receipt_id: str):
        from sqlalchemy import delete

        try:
            receipt_repo.delete(receipt_id)
        except KeyError as exc:
            raise HTTPException(404, "Receipt not found") from exc
        with db.engine.begin() as conn:
            conn.execute(
                delete(refresh_requests).where(refresh_requests.c.receipt_id == receipt_id)
            )
        return {"status": "deleted"}

    return app


app = create_app()
