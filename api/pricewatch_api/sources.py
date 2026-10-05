import json
from datetime import UTC, datetime
from decimal import Decimal
from html.parser import HTMLParser
from zoneinfo import ZoneInfo

import httpx

from .barcodes import source_ean
from .models import PriceInput

ALDI_URL = "https://www.aldi-nord.de/angebote.html"


class SourceError(Exception):
    pass


class NextDataParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.capture = False
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "script" and dict(attrs).get("id") == "__NEXT_DATA__":
            self.capture = True

    def handle_endtag(self, tag):
        if tag == "script":
            self.capture = False

    def handle_data(self, data):
        if self.capture:
            self.parts.append(data)


def cents(value) -> int:
    amount = Decimal(str(value)) * 100
    if not amount.is_finite() or amount < 0 or amount != amount.to_integral_value():
        raise ValueError("Invalid EUR amount")
    return int(amount)


def parse_aldi(html: str, observed_at: datetime) -> list[PriceInput]:
    parser = NextDataParser()
    parser.feed(html)
    try:
        data = json.loads("".join(parser.parts))["props"]["pageProps"]["apiData"]
        data = json.loads(data) if isinstance(data, str) else data
        products = next(
            entry[1]["res"]["algoliaDataMap"] for entry in data if entry[0] == "OFFER_GET"
        )
        result = []
        for product in products.values():
            if product.get("isRecall") or not product.get("isAvailable"):
                continue
            price = product["currentPrice"]
            # Epoch boundaries are local sale dates, not UTC dates.
            valid_from = datetime.fromtimestamp(price["validFrom"], ZoneInfo("Europe/Berlin"))
            valid_until = datetime.fromtimestamp(price["validUntil"], ZoneInfo("Europe/Berlin"))
            unit_value = unit = None
            for base in price.get("basePrice", []):
                unit = {"kg": "kg", "Liter": "l", "l": "l", "Stück": "item"}.get(
                    base["basePriceScale"]
                )
                if unit:
                    unit_value = Decimal(str(base["basePriceValue"])) * 100
                    break
            # UVP / competitor reference prices are not retailer regular prices.
            strike = price.get("strikePrice", {})
            conditions = product.get("shortDescription")
            if strike:
                reference = (
                    f"Referenzpreis ({strike.get('strikePriceLabel', 'unbekannt')}): "
                    f"{strike['strikePriceValue']} EUR"
                )
                conditions = f"{conditions}; {reference}" if conditions else reference
            result.append(
                PriceInput(
                    retailer="aldi_nord",
                    source_product_id=str(product["objectID"]),
                    name=product["name"],
                    brand=product.get("brandName"),
                    ean=source_ean(product),
                    kind="offer",
                    price_cents=cents(price["priceValue"]),
                    deposit_cents=(
                        cents(product["depositValue"]) if "depositValue" in product else None
                    ),
                    package_label=product.get("salesUnit"),
                    unit_price_cents=unit_value,
                    unit_price_unit=unit if unit_value is not None else None,
                    valid_from=valid_from.date(),
                    valid_until=valid_until.date(),
                    scope="chain_advertised",
                    source_url=ALDI_URL,
                    observed_at=observed_at,
                    conditions=conditions[:300] if conditions else None,
                )
            )
        if not result:
            raise ValueError("No available priced products")
        return result
    except (KeyError, ValueError, TypeError, StopIteration, OverflowError, OSError) as exc:
        # Fail the whole sync rather than silently publishing a partial scrape.
        raise SourceError("ALDI response format changed or contains invalid prices") from exc


def fetch_aldi() -> list[PriceInput]:
    try:
        with httpx.Client(
            timeout=30,
            follow_redirects=True,
            headers={"User-Agent": "PriceWatch/0.1 (price catalog)"},
        ) as client:
            response = client.get(ALDI_URL)
            response.raise_for_status()
        return parse_aldi(response.text, datetime.now(UTC))
    except httpx.HTTPStatusError as exc:
        raise SourceError(f"ALDI returned HTTP {exc.response.status_code}") from exc
    except httpx.RequestError as exc:
        raise SourceError("ALDI request failed (network/timeout)") from exc
