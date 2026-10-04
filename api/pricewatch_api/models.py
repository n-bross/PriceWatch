from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

from .barcodes import valid_ean


class Retailer(StrEnum):
    ALDI_NORD = "aldi_nord"
    ALDI_SUED = "aldi_sued"
    REWE = "rewe"
    NETTO = "netto"
    LIDL = "lidl"
    EDEKA = "edeka"
    PENNY = "penny"
    KAUFLAND = "kaufland"
    NORMA = "norma"
    GLOBUS = "globus"
    TEGUT = "tegut"
    HIT = "hit"
    COMBI = "combi"
    NAHKAUF = "nahkauf"
    ALNATURA = "alnatura"
    NETTO_DOG = "netto_dog"


RETAILERS = {
    "aldi_nord": "ALDI Nord",
    "aldi_sued": "ALDI Süd",
    "rewe": "REWE",
    "netto": "Netto Marken-Discount",
    "lidl": "Lidl",
    "edeka": "EDEKA",
    "penny": "Penny",
    "kaufland": "Kaufland",
    "norma": "NORMA",
    "globus": "GLOBUS",
    "tegut": "tegut",
    "hit": "HIT",
    "combi": "Combi",
    "nahkauf": "nahkauf",
    "alnatura": "Alnatura",
    "netto_dog": "Netto mit Hund",
}
Text = Annotated[str, Field(min_length=1, max_length=300)]
Zip = Annotated[str, Field(pattern=r"^\d{5}$")]


class PriceInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    retailer: Retailer
    source_product_id: Text
    name: Text
    brand: Text | None = None
    # EAN is optional: similarly named products are not necessarily identical.
    ean: Annotated[str, Field(pattern=r"^(\d{8}|\d{13}|\d{14})$")] | None = None
    kind: Literal["regular", "offer"]
    price_cents: Annotated[int, Field(strict=True, ge=0, le=100_000_000)]
    regular_price_cents: Annotated[int, Field(strict=True, ge=0)] | None = None
    deposit_cents: Annotated[int, Field(strict=True, ge=0)] | None = None
    currency: Literal["EUR"] = "EUR"
    package_label: Text | None = None
    # Already normalized to price per kg, litre or item by the source.
    unit_price_cents: Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=2)] | None = None
    unit_price_unit: Literal["kg", "l", "item"] | None = None
    valid_from: date
    valid_until: date
    scope: Literal["chain_advertised", "postal_code", "store"]
    postal_code: Zip | None = None
    store_id: Text | None = None
    requires_membership: bool = False
    conditions: Text | None = None
    source_url: HttpUrl
    observed_at: datetime

    @field_validator("ean")
    @classmethod
    def barcode_checksum(cls, value: str | None) -> str | None:
        if value is not None and not valid_ean(value):
            raise ValueError("ean must be an EAN-8, EAN-13 or GTIN-14 with a valid check digit")
        return value

    @field_validator("observed_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observed_at needs a timezone")
        from datetime import UTC, timedelta

        if value > datetime.now(UTC) + timedelta(minutes=5):
            raise ValueError("observed_at cannot be in the future")
        return value

    @model_validator(mode="after")
    def consistent(self):
        if self.valid_until < self.valid_from:
            raise ValueError("valid_until must be on or after valid_from")
        if (self.unit_price_cents is None) != (self.unit_price_unit is None):
            raise ValueError("unit price requires both value and unit")
        if self.scope == "postal_code" and not self.postal_code:
            raise ValueError("postal_code scope requires postal_code")
        if self.scope == "store" and not self.store_id:
            raise ValueError("store scope requires store_id")
        if self.scope == "chain_advertised" and (self.postal_code or self.store_id):
            raise ValueError("chain_advertised scope cannot contain a store or postal code")
        if self.scope == "postal_code" and self.store_id:
            raise ValueError("use store scope for store-specific prices")
        return self


class ImportBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")]
    prices: Annotated[list[PriceInput], Field(min_length=1, max_length=1000)]


class Price(PriceInput):
    id: str
    source: str
    checkout_price_cents: int | None
    ean_origin: Literal["source", "confirmed_mapping"] | None = None
    barcode_scope: Literal["global_candidate", "restricted_circulation"] | None = None


class PricePage(BaseModel):
    items: list[Price]
    total: int
    limit: int
    offset: int
    price_observations: dict | None = None
