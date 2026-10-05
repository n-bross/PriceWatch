"""Import explicitly reviewed prices from a market-selected REWE browser session."""

from datetime import UTC, date, datetime
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

from .barcodes import valid_ean
from .catalog import ProductInput, ProductRepository
from .models import PriceInput
from .observations import ObservationRepository


class BrowserProduct(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    source_product_id: str = Field(min_length=1, max_length=300)
    name: str = Field(min_length=1, max_length=300)
    ean: str | None = None
    brand: str | None = Field(default=None, max_length=300)
    package_label: str | None = Field(default=None, max_length=300)
    price_cents: int = Field(strict=True, ge=0, le=100_000_000)
    kind: Literal["regular", "offer", "unknown"] = "unknown"
    requires_membership: bool | None = None
    valid_from: date | None = None
    valid_until: date | None = None
    bonus_credit_cents: int | None = Field(default=None, strict=True, ge=0, le=100_000_000)
    bonus_credit_percent: float | None = Field(default=None, ge=0, le=100, allow_inf_nan=False)
    conditions_text: str | None = Field(default=None, max_length=1000)
    source_store_id: str | None = Field(default=None, max_length=300)
    source_offer_week: str | None = Field(default=None, pattern=r"^\d{4}/\d{2}$")
    source_url: HttpUrl

    @field_validator("ean")
    @classmethod
    def barcode(cls, value):
        if value is not None and not valid_ean(value):
            raise ValueError("Provide an explicit, checksum-valid barcode or omit ean")
        return value

    @field_validator("source_url")
    @classmethod
    def official_source(cls, value):
        if value.scheme != "https" or value.host not in ("rewe.de", "www.rewe.de"):
            raise ValueError("A REWE HTTPS product source is required")
        return value

    @model_validator(mode="after")
    def valid_period(self):
        if self.valid_from and self.valid_until and self.valid_from > self.valid_until:
            raise ValueError("Offer end must not precede its start")
        return self


class ReweBrowserBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    store_id: str = Field(min_length=1, max_length=300)
    postal_code: str = Field(pattern=r"^\d{5}$")
    channel: Literal["delivery", "pickup", "store", "advertised"]
    captured_at: datetime
    # Confirms selected market, shopping channel and visible prices, not global validity.
    context_confirmed: Literal[True]
    products: list[BrowserProduct] = Field(min_length=1, max_length=1000)

    @field_validator("captured_at")
    @classmethod
    def actual_capture_time(cls, value):
        if value.utcoffset() is None or value > datetime.now(UTC):
            raise ValueError("captured_at must have a timezone and cannot be in the future")
        return value

    @model_validator(mode="after")
    def matching_market(self):
        if any(p.source_store_id and p.source_store_id != self.store_id for p in self.products):
            raise ValueError("Offer market must match the import market")
        return self


def import_browser_prices(db, batch):
    entries, products = [], []
    for product in batch.products:
        entries.append(
            {
                **product.model_dump(mode="json"),
                "source": "rewe_browser",
                "retailer": "REWE",
                "store_id": batch.store_id,
                "postal_code": batch.postal_code,
                "channel": batch.channel,
                "scope": "store_channel",
                "price_date": batch.captured_at.astimezone(ZoneInfo("Europe/Berlin"))
                .date()
                .isoformat(),
                "captured_at": batch.captured_at.isoformat(),
            }
        )
        if product.ean:
            products.append(
                ProductInput(
                    ean=product.ean,
                    name=product.name,
                    brand=product.brand,
                    package_label=product.package_label,
                    countries=["en:germany"],
                    reported_stores="REWE",
                    source_url=product.source_url,
                    source_updated_at=batch.captured_at,
                )
            )
    # Only explicitly dated, market-matched advertised offers enter the current-price API.
    # Delivery/pickup observations never become physical-store prices.
    offers = [
        PriceInput(
            retailer="rewe",
            source_product_id=p.source_product_id,
            name=p.name,
            ean=p.ean,
            brand=p.brand,
            package_label=p.package_label,
            kind="offer",
            price_cents=p.price_cents,
            valid_from=p.valid_from,
            valid_until=p.valid_until,
            scope="store",
            postal_code=batch.postal_code,
            store_id=batch.store_id,
            requires_membership=p.requires_membership,
            conditions=p.conditions_text[:300] if p.conditions_text else None,
            source_url=p.source_url,
            observed_at=batch.captured_at,
        )
        for p in batch.products
        if batch.channel == "advertised"
        and p.kind == "offer"
        and p.source_store_id == batch.store_id
        and p.valid_from
        and p.valid_until
        and p.requires_membership is not None
    ]
    processed = ObservationRepository(db).save(entries)
    published = db.import_prices("rewe_browser", offers) if offers else 0
    ProductRepository(db).upsert(products, source="retailer_observation")
    db.record_run(
        "rewe_browser",
        "ok",
        processed,
        f"Reviewed {batch.channel} prices for market {batch.store_id}",
    )
    return {
        "processed": processed,
        "published_offers": published,
        "store_id": batch.store_id,
        "channel": batch.channel,
    }
