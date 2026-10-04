"""Public website data, not official, contractually stable partner APIs."""

import json
import math
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from functools import lru_cache
from html import unescape
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from .barcodes import source_ean
from .models import PriceInput
from .sources import SourceError, cents

PENNY_URL = "https://www.penny.de/angebote"
KAUFLAND_URL = "https://filiale.kaufland.de/angebote.html"
ALDI_SUED_URL = "https://www.aldi-sued.de/angebote"


def get(client: httpx.Client, url: str):
    try:
        response = client.get(url)
        response.raise_for_status()
        return response
    except httpx.HTTPStatusError as exc:
        raise SourceError(f"Source returned HTTP {exc.response.status_code}: {url}") from exc
    except httpx.RequestError as exc:
        raise SourceError(f"Source network/timeout error: {url}") from exc


def client():
    return httpx.Client(
        timeout=30, follow_redirects=True, headers={"User-Agent": "PriceWatch/0.1 (price catalog)"}
    )


def base_price(text: str | None):
    if not text:
        return None, None
    match = re.search(r"1\s*(kg|l|Liter|Stück)\s*=\s*(\d+[.,]\d{2})", text)
    if not match:
        return None, None
    return Decimal(match[2].replace(",", ".")) * 100, {"Liter": "l", "Stück": "item"}.get(
        match[1], match[1]
    )


def clean(text):
    return unescape(text or "").strip()


def decorated_cents(value: str):
    match = re.fullmatch(r"(\d+[.,]\d{2})[¹²³⁴⁵⁶⁷⁸⁹⁰*]*", value)
    if not match:
        raise ValueError("Ambiguous price text")
    return cents(match[1].replace(",", "."))


def parse_kaufland(html: str, observed_at: datetime) -> list[PriceInput]:
    decoder = json.JSONDecoder()
    categories = []
    for match in re.finditer(r'\]\s*=\s*(\{"component")', html):
        obj, _ = decoder.raw_decode(html[match.start(1) :])
        if obj.get("component") == "StandaloneOfferCategory":
            categories.extend(obj["props"]["offerData"])
    if not categories:
        raise SourceError("Kaufland offer data missing; website format changed")
    items = {}
    try:
        for category in categories:
            for offer in category["offers"]:
                if offer.get("price") is None or offer.get("bbyMessage"):
                    continue
                unit_value, unit = base_price(offer.get("basePrice"))
                common = dict(
                    retailer="kaufland",
                    source_product_id=offer["offerId"],
                    ean=source_ean(offer),
                    name=clean(" ".join(filter(None, [offer.get("title"), offer.get("subtitle")]))),
                    kind="offer",
                    price_cents=cents(offer["price"]),
                    package_label=clean(offer.get("unit")) or None,
                    valid_from=offer["dateFrom"],
                    valid_until=offer["dateTo"],
                    unit_price_cents=unit_value,
                    unit_price_unit=unit,
                    scope="chain_advertised",
                    source_url=KAUFLAND_URL,
                    observed_at=observed_at,
                    conditions=clean(offer.get("detailDescription"))[:300] or None,
                )
                item = PriceInput(**common)
                items[(item.source_product_id, item.valid_from)] = item
                # Card prices are separate and excluded from default queries.
                if offer.get("loyaltyFormattedPrice"):
                    match = re.fullmatch(r"(\d+[.,]\d{2})\*?", offer["loyaltyFormattedPrice"])
                    if match:
                        value, unit = base_price(offer.get("loyaltyBasePrice"))
                        card = PriceInput(
                            **{
                                **common,
                                "source_product_id": offer["offerId"] + ":card",
                                "price_cents": cents(match[1].replace(",", ".")),
                                "unit_price_cents": value,
                                "unit_price_unit": unit,
                                "requires_membership": True,
                                "conditions": "Nur mit Kaufland Card",
                            }
                        )
                        items[(card.source_product_id, card.valid_from)] = card
        if not items:
            raise ValueError("No priced offers")
    except (KeyError, ValueError, TypeError) as exc:
        raise SourceError("Invalid Kaufland offer format") from exc
    return list(items.values())


def fetch_kaufland() -> list[PriceInput]:
    with client() as c:
        return parse_kaufland(get(c, KAUFLAND_URL).text, datetime.now(UTC))


def penny_categories(html: str):
    soup = BeautifulSoup(html, "html.parser")
    weeks = soup.select_one("[data-current-week]")
    if weeks is None:
        raise SourceError("Penny current week missing")
    year, week = map(int, weeks["data-current-week"].split("-"))
    monday = date.fromisocalendar(year, week, 1)
    days = {"Mo": 0, "Di": 1, "Mi": 2, "Do": 3, "Fr": 4, "Sa": 5, "So": 6}
    categories = []
    for section in soup.select(".tabs__content--current-week [data-category-name]"):
        dates = re.search(
            r"Diese Woche\s+(Mo|Di|Mi|Do|Fr|Sa|So)-(Mo|Di|Mi|Do|Fr|Sa|So)",
            section.get_text(" ", strip=True),
        )
        if dates is None:
            raise SourceError("Penny category validity missing; refusing guessed sale dates")
        categories.append(
            (
                section["data-category-name"],
                monday + timedelta(days=days[dates[1]]),
                monday + timedelta(days=days[dates[2]]),
            )
        )
    if not categories:
        raise SourceError("Penny current categories missing")
    return weeks["data-current-week"], categories


def parse_penny_category(
    data: dict,
    *,
    url: str,
    valid_from: date,
    valid_until: date,
    observed_at: datetime,
    store: dict | None = None,
):
    items = []
    try:
        for tile in data["offerTiles"]:
            # Content teasers have no product price; variable/minimum-quantity prices
            # cannot be treated as a one-pack comparison.
            if not tile.get("price") or tile.get("onlyOnline"):
                continue
            if tile.get("priceFrom") or tile.get("multiBuy") or tile.get("actionPriceFrom"):
                continue
            if re.fullmatch(r"\d+(?:[.,]\d+)?\s*%\s*Rabatt", tile["price"], re.I):
                continue  # A category-wide percentage is not a product's EUR price.
            app_only = tile.get("primaryType") == "promo"
            value, unit = base_price(
                tile.get("benefitGroundPrice") if app_only else tile.get("basePrice")
            )
            common = dict(
                retailer="penny",
                source_product_id=tile["uuid"] + (":app" if app_only else ""),
                ean=source_ean(tile),
                name=clean(tile["title"]).rstrip("*"),
                kind="offer",
                price_cents=decorated_cents(tile["price"]),
                package_label=tile.get("quantity"),
                unit_price_cents=value,
                unit_price_unit=unit,
                valid_from=valid_from,
                valid_until=valid_until,
                scope="store" if store else "chain_advertised",
                store_id=str(store["wwIdent"]) if store else None,
                postal_code=store["zipCode"] if store else None,
                source_url=url,
                observed_at=observed_at,
                requires_membership=app_only,
                conditions="Nur mit PENNY App; Couponbedingungen beachten" if app_only else None,
            )
            items.append(PriceInput(**common))
            if tile.get("benefitPrice") and not app_only:
                match = re.match(r"^(\d+[.,]\d{2})(?:[^\d.,]|$)", tile["benefitPrice"])
                if match:
                    value, unit = base_price(tile.get("benefitGroundPrice"))
                    items.append(
                        PriceInput(
                            **{
                                **common,
                                "source_product_id": tile["uuid"] + ":app",
                                "price_cents": cents(match[1].replace(",", ".")),
                                "unit_price_cents": value,
                                "unit_price_unit": unit,
                                "requires_membership": True,
                                "conditions": "Nur mit PENNY App; Couponbedingungen beachten",
                            }
                        )
                    )
    except (KeyError, ValueError, TypeError) as exc:
        raise SourceError("Invalid Penny price data") from exc
    return items


@lru_cache(maxsize=256)
def postcode_location(postal_code: str):
    with client() as c:
        data = get(c, f"https://api.zippopotam.us/de/{postal_code}").json()
    try:
        # Some PLZs cover several places; use their center, not an exact user location.
        points = [(float(p["latitude"]), float(p["longitude"])) for p in data["places"]]
        return (sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points))
    except (KeyError, ValueError, TypeError, ZeroDivisionError) as exc:
        raise SourceError("Postal code coordinates unavailable") from exc


def distance_km(origin, target):
    lat1, lon1, lat2, lon2 = map(math.radians, [*origin, *target])
    a = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 6371 * 2 * math.asin(min(1, math.sqrt(a)))


def penny_stores(postal_code: str, radius_km: int = 30, limit: int = 3):
    center = postcode_location(postal_code)
    with client() as c:
        markets = get(c, "https://www.penny.de/.rest/market").json()
    stores = []
    for m in markets:
        if not m.get("latitude") or not m.get("longitude") or not m.get("sellingRegion"):
            continue
        d = distance_km(center, (float(m["latitude"]), float(m["longitude"])))
        if d <= radius_km:
            stores.append({**m, "distance_km": round(d, 2)})
    return sorted(stores, key=lambda m: (m["distance_km"], m["wwIdent"]))[:limit]


def penny_upcoming_categories(html: str):
    soup = BeautifulSoup(html, "html.parser")
    weeks = soup.select_one("[data-next-week]")
    if not weeks:
        return None, []
    year, week = map(int, weeks["data-next-week"].split("-"))
    monday = date.fromisocalendar(year, week, 1)
    days = {"Mo": 0, "Di": 1, "Mi": 2, "Do": 3, "Fr": 4, "Sa": 5, "So": 6}
    categories = []
    for section in soup.select(".tabs__content--next-week [data-category-name]"):
        dates = re.search(
            r"Nächste Woche\s+(Mo|Di|Mi|Do|Fr|Sa|So)-(Mo|Di|Mi|Do|Fr|Sa|So)",
            section.get_text(" ", strip=True),
        )
        if dates:
            categories.append(
                (
                    section["data-category-name"],
                    monday + timedelta(days=days[dates[1]]),
                    monday + timedelta(days=days[dates[2]]),
                )
            )
    return weeks["data-next-week"], categories


def fetch_penny(postal_code: str | None = None, radius_km: int = 30, limit: int = 3):
    stores = penny_stores(postal_code, radius_km, limit) if postal_code else []
    if postal_code and not stores:
        raise SourceError("No Penny stores with offer regions found within the requested radius")
    with client() as c:
        html = get(c, PENNY_URL).text
        week, categories = penny_categories(html)
        next_week, upcoming = penny_upcoming_categories(html)
        observed_at = datetime.now(UTC)
        regions = {m["sellingRegion"] for m in stores} if stores else {None}
        jobs = [
            (region, sale_week, category, start, end)
            for region in sorted(regions, key=str)
            for sale_week, batch in [(week, categories), (next_week, upcoming)]
            for category, start, end in batch
        ]

        def fetch(job):
            region, sale_week, category, start, end = job
            url = f"https://www.penny.de/.rest/offers/by-category/{sale_week}/{category}"
            if region:
                url += f"?region={region}"
            return job, url, get(c, url).json()

        # Requests are bounded to four connections; a failed category aborts the snapshot.
        with ThreadPoolExecutor(max_workers=4) as pool:
            responses = list(pool.map(fetch, jobs))
    groups = {}
    for store in stores or [None]:
        items = {}
        for (region, sale_week, category, start, end), url, data in responses:
            if store and region != store["sellingRegion"]:
                continue
            for item in parse_penny_category(
                data,
                url=url,
                valid_from=start,
                valid_until=end,
                observed_at=observed_at,
                store=store,
            ):
                items[(item.source_product_id, item.valid_from)] = item
        if not items:
            raise SourceError("No Penny prices extracted")
        source = f"penny:store:{store['wwIdent']}" if store else "penny"
        groups[source] = list(items.values())
    return groups, stores


def parse_aldi_sued(html: str, observed_at: datetime):
    """Only the explicitly dated weekly section, never guess expiry of 'ab' offers."""
    soup = BeautifulSoup(html, "html.parser")
    try:
        flat = json.loads(soup.select_one("#__NUXT_DATA__").string)

        def decode(index):
            if not isinstance(index, int):
                return index
            if index < 0:
                return None
            value = flat[index]
            if isinstance(value, dict):
                return {k: decode(v) for k, v in value.items()}
            if isinstance(value, list):
                return [decode(v) for v in value]
            return value

        products = {
            decode(i)["sku"]: decode(i)
            for i, value in enumerate(flat)
            if isinstance(value, dict) and "sku" in value and "price" in value
        }
        items = []
        for block in soup.select(".product-teaser-list"):
            heading = block.select_one("h2")
            if not heading or "Wochenangebote" not in heading.get_text():
                continue
            dates = re.findall(r"(\d{1,2})\.(\d{1,2})\.", heading.get_text())
            if len(dates) != 2:
                raise ValueError("Explicit weekly date range missing")
            candidates = [
                date(observed_at.year + delta, int(dates[0][1]), int(dates[0][0]))
                for delta in [-1, 0, 1]
            ]
            start = min(candidates, key=lambda d: abs((d - observed_at.date()).days))
            end = date(start.year, int(dates[1][1]), int(dates[1][0]))
            if end < start:
                end = end.replace(year=end.year + 1)
            if (end - start).days > 7 or abs((start - observed_at.date()).days) > 14:
                raise ValueError("Implausible weekly date range")
            for tile in block.select('[data-test="product-tile"]'):
                link = tile.select_one('a[href*="/produkt/"]')
                sku = re.search(r"-(\d+)$", link["href"])[1]
                product = products[sku]
                p = product["price"]
                unit_text = p.get("comparisonDisplay") or ""
                unit_match = re.search(r"€/1\s*(kg|l)", unit_text)
                unit_value = p.get("comparison") if unit_match else None
                unit = unit_match[1] if unit_match else None
                package = product.get("sellingSize") or product.get("sellingUnitDisplay")
                conditions = "Beworbenes Wochenangebot; Verfügbarkeit in der Filiale prüfen"
                if product.get("isRandomWeight"):
                    # Loose produce uses perUnitDisplay, not comparisonDisplay.
                    basis = re.fullmatch(r"1\s*(kg|l)", p.get("perUnitDisplay") or "")
                    if not basis:
                        raise ValueError("Unsupported loose-product sale unit")
                    unit, unit_value = basis[1], p["amountRelevant"]
                    package = f"1 {unit} (lose; nach Gewicht)"
                    conditions += f"; Preis pro {unit}, Kassenbetrag nach Gewicht"
                elif not package and product.get("quantityUnit") == "ea":
                    package = "1 Stück"
                    unit, unit_value = "item", p["amountRelevant"]
                if product.get("discontinued"):
                    continue
                # notForSale marks unavailable online checkout, not absence from stores.
                items.append(
                    PriceInput(
                        retailer="aldi_sued",
                        source_product_id=sku,
                        name=product["name"],
                        brand=product.get("brandName"),
                        ean=source_ean(product),
                        kind="offer",
                        price_cents=p["amountRelevant"],
                        deposit_cents=p.get("bottleDeposit"),
                        package_label=package,
                        unit_price_cents=unit_value,
                        unit_price_unit=unit,
                        valid_from=start,
                        valid_until=end,
                        scope="chain_advertised",
                        source_url=urljoin(ALDI_SUED_URL, link["href"]),
                        observed_at=observed_at,
                        conditions=conditions,
                    )
                )
        if not items:
            raise ValueError("No explicitly dated weekly offers")
        return items
    except (AttributeError, IndexError, KeyError, ValueError, TypeError) as exc:
        raise SourceError("ALDI Süd weekly offer format changed") from exc


def fetch_aldi_sued():
    with httpx.Client(timeout=30, follow_redirects=True) as c:
        return parse_aldi_sued(get(c, ALDI_SUED_URL).text, datetime.now(UTC))
