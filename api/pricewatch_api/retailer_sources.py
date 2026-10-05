"""Deterministic public retailer offer parsers and audit checks.

Extracts structured supermarket offers from verifiable public HTML listings.
Strictly excludes crossed-out prices (UVP), unit prices, loyalty app
promotions, and percentage discounts. Never invents expiry dates when only an
'ab' start date is provided, and never guesses or coerces EANs.
"""

import html
import re
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup

from .barcodes import valid_ean
from .catalog import ProductInput, ProductRepository
from .database import Database

BERLIN_TZ = ZoneInfo("Europe/Berlin")
DEFAULT_NORMA_URL = "https://www.norma-online.de/de/angebote/"


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    text = re.sub(r"<[^>]+>", " ", value)
    text = html.unescape(text)
    return " ".join(text.split())


def parse_german_price(price_str: str) -> int:
    """Converts a German decimal price string (e.g. '12,99', '-,99') to cents."""
    cleaned = price_str.strip().replace("–", "0").replace("-", "0").replace(",", ".")
    amount = Decimal(cleaned)
    if not amount.is_finite() or amount < 0 or amount > 1_000_000:
        raise ValueError(f"Invalid price amount: {price_str}")
    return int((amount * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def extract_dates(text: str, url: str = "") -> tuple[str | None, str | None]:
    """Extract explicit validity dates.

    Conservative principle: If only a start date ('ab [tag], DD.MM.YY') is
    present, valid_from is set and valid_until remains None. Expiry is NEVER
    invented.
    """
    valid_from: str | None = None
    valid_until: str | None = None

    # 1. Explicit range: 'vom DD.MM. bis DD.MM.YYYY'
    range_match = re.search(
        r"vom\s+(\d{2})\.(\d{2})\.(?:(\d{4})|(\d{2}))?\s+bis\s+"
        r"(\d{2})\.(\d{2})\.(\d{2,4})",
        text,
        re.IGNORECASE,
    )
    if range_match:
        f_d, f_m, f_y4, f_y2, u_d, u_m, u_y = range_match.groups()
        year_until = int(u_y) if len(u_y) == 4 else 2000 + int(u_y)
        year_from = year_until
        if f_y4:
            year_from = int(f_y4)
        elif f_y2:
            year_from = 2000 + int(f_y2)
        try:
            valid_from = date(year_from, int(f_m), int(f_d)).isoformat()
            valid_until = date(year_until, int(u_m), int(u_d)).isoformat()
            return valid_from, valid_until
        except ValueError:
            pass

    # 2. 'ab' start date from URL or text (e.g. /ab-freitag,-02.10.26/)
    combined = f"{url} {text}"
    ab_match = re.search(
        r"ab-(?:[a-zäöü]+,-)?(\d{2})\.(\d{2})\.(\d{2,4})|"
        r"ab\s+(?:[A-Za-zÄÖÜäöü]+,?\s+)?(\d{2})\.(\d{2})\.(\d{2,4})",
        combined,
        re.IGNORECASE,
    )
    if ab_match:
        d = ab_match.group(1) or ab_match.group(4)
        m = ab_match.group(2) or ab_match.group(5)
        y = ab_match.group(3) or ab_match.group(6)
        year = int(y) if len(y) == 4 else 2000 + int(y)
        try:
            valid_from = date(year, int(m), int(d)).isoformat()
        except ValueError:
            valid_from = None

    return valid_from, valid_until


def parse_norma_html(
    html_content: str,
    base_url: str = DEFAULT_NORMA_URL,
    price_date: str | None = None,
) -> list[dict]:
    """Parses NORMA promotional offer cards from structured HTML.

    Extracts exact shelf prices from .produktBox-cont-wrapper-price while
    explicitly excluding:
      - Crossed-out UVP reference prices (.produktBox-cont-wrapper-uvp)
      - Unit prices (.produktBox-txt-price)
      - Promotional percentage discounts (.produktBox-cont-wrapper-billiger)
      - App-only conditions inside banner images
    EAN is captured only if an unambiguous, checksum-valid barcode attribute
    exists.
    """
    if not price_date:
        price_date = datetime.now(BERLIN_TZ).date().isoformat()

    results = []
    seen_keys = set()
    soup = BeautifulSoup(html_content, "html.parser")

    # Target <article class="... produktBoxContainer ..." id="of_...">
    articles = []
    for article in soup.find_all("article"):
        classes = article.get("class") or []
        class_str = " ".join(classes)
        if "produktBox" in class_str or article.find(class_=lambda c: c and "produktBox" in c):
            articles.append(article)

    for article in articles:
        # 1. Deterministic Card Identifier
        card_id = article.get("id") or ""
        source_product_id = card_id.removeprefix("of_") if card_id else None

        # 2. Offer URL & public card fragment
        a_tag = article.find("a", href=True)
        href = a_tag["href"].strip() if a_tag else ""
        if not href and not source_product_id:
            continue

        full_url = urljoin(base_url, href) if href else base_url
        source_url = f"{full_url}#{card_id}" if card_id and "#" not in full_url else full_url

        # 3. Product Headline and Supplier (Brand)
        headline_el = article.find(class_=lambda c: c and "produktBox-txt-headline" in c)
        headline = clean_text(headline_el.get_text()) if headline_el else ""
        if not headline:
            continue

        supplier_el = article.find(class_=lambda c: c and "supplier" in c)
        brand = clean_text(supplier_el.get_text()) if supplier_el else None

        if brand and brand.lower() not in headline.lower():
            name = f"{brand} {headline}".strip()
        else:
            name = headline

        # 4. Package label / Content amount
        package_label = None
        inh_el = article.find(class_=lambda c: c and "produktBox-txt-inh" in c)
        if inh_el:
            package_label = clean_text(inh_el.get_text())
        else:
            overlay_el = article.find(class_=lambda c: c and "inhalt" in c)
            if overlay_el:
                package_label = clean_text(overlay_el.get_text())

        # 5. Exact Shelf Price - STRICT ISOLATION from UVP, unit prices, discounts
        price_wrapper = article.find(class_=lambda c: c and "produktBox-cont-wrapper-price" in c)
        if not price_wrapper:
            continue

        price_cents = None

        # Priority 1: explicit aria-label="12,99 Euro"
        aria_candidates = [price_wrapper] + price_wrapper.find_all(attrs={"aria-label": True})
        for candidate in aria_candidates:
            aria_val = candidate.get("aria-label", "")
            m = re.search(r"([0-9–\-]+[.,][0-9]{2})", aria_val)
            if m:
                try:
                    price_cents = parse_german_price(m.group(1))
                    break
                except (ValueError, InvalidOperation):
                    pass

        # Priority 2: visible price text inside wrapper, stripping superscripts
        if price_cents is None:
            wrapper_copy = BeautifulSoup(str(price_wrapper), "html.parser")
            for sup in wrapper_copy.find_all("sup"):
                sup.decompose()
            text = clean_text(wrapper_copy.get_text())
            m = re.search(r"([0-9–\-]+[.,][0-9]{2})", text)
            if m:
                try:
                    price_cents = parse_german_price(m.group(1))
                except (ValueError, InvalidOperation):
                    pass

        if price_cents is None or price_cents <= 0:
            continue

        # 6. Conditions & Reference Text (UVP / Billiger / Unit price)
        conditions_parts = []
        uvp_el = article.find(class_=lambda c: c and "produktBox-cont-wrapper-uvp" in c)
        if uvp_el:
            uvp_text = clean_text(uvp_el.get_text())
            if uvp_text:
                conditions_parts.append(uvp_text)

        billiger_el = article.find(class_=lambda c: c and "produktBox-cont-wrapper-billiger" in c)
        if billiger_el:
            title_text = clean_text(billiger_el.get("title", ""))
            discount_text = clean_text(billiger_el.get_text())
            if discount_text:
                if title_text:
                    conditions_parts.append(f"{discount_text} ({title_text})")
                else:
                    conditions_parts.append(discount_text)

        conditions_text = "; ".join(conditions_parts) if conditions_parts else None

        # 7. Validity Dates (never invent expiry from an 'ab' start date;
        # exclude banner images containing app-exclusive promotion text)
        article_copy = BeautifulSoup(str(article), "html.parser")
        for img in article_copy.find_all("img"):
            img.decompose()
        clean_article_text = clean_text(article_copy.get_text())
        valid_from, valid_until = extract_dates(clean_article_text, href)

        # 8. Checksum-valid EAN if explicitly present in attributes (never guessed)
        ean = None
        for el in [article] + article.find_all(True):
            for attr in ("data-ean", "data-gtin", "gtin", "ean"):
                if el.has_attr(attr):
                    val = str(el[attr]).strip()
                    if valid_ean(val):
                        ean = val
                        break
            if ean:
                break

        dedup_key = (source_product_id or source_url, price_cents, valid_from)
        if dedup_key in seen_keys:
            continue
        seen_keys.add(dedup_key)

        results.append(
            {
                "source": "retailer_website_v2",
                "retailer": "NORMA",
                "source_product_id": source_product_id or f"norma_{len(results) + 1}",
                "name": name,
                "brand": brand,
                "ean": ean,
                "price_cents": price_cents,
                "price_date": price_date,
                "scope": "unknown",
                "kind": "offer",
                "source_url": source_url,
                "valid_from": valid_from,
                "valid_until": valid_until,
                "package_label": package_label,
                "conditions_text": conditions_text,
            }
        )

    return results


def audit_retailer_html(retailer_id: str, html_content: str) -> dict:
    """Audits an HTML document to verify if deterministic offer cards exist.

    Distinguishes verifiable HTML offer cards from leaflet viewers (1kcloud,
    FlippingBook, e-paper viewers) and sites requiring branch/market selection.
    """
    lowered = html_content.lower()

    if retailer_id == "norma":
        cards = parse_norma_html(html_content)
        if cards:
            return {
                "retailer_id": retailer_id,
                "supports_structured_offers": True,
                "source_type": "structured_html",
                "observations_found": len(cards),
                "reason": (
                    f"Structured HTML offer cards found (.produktBoxContainer): "
                    f"{len(cards)} items parsed"
                ),
            }
        return {
            "retailer_id": retailer_id,
            "supports_structured_offers": False,
            "source_type": "unsupported_format",
            "observations_found": 0,
            "reason": "NORMA HTML format changed or missing product cards",
        }

    if "1kcloud" in lowered or "wasgau-dlog" in lowered:
        return {
            "retailer_id": retailer_id,
            "supports_structured_offers": False,
            "source_type": "leaflet_viewer_only",
            "observations_found": 0,
            "reason": (
                "Third-party 1kcloud leaflet viewer iframe; no structured HTML product cards"
            ),
        }

    if "markt auswählen" in lowered or "filiale wählen" in lowered:
        return {
            "retailer_id": retailer_id,
            "supports_structured_offers": False,
            "source_type": "requires_store_selection",
            "observations_found": 0,
            "reason": (
                "Regional store branch selection required; "
                "no national catalog available on landing page"
            ),
        }

    if "blätterprospekt" in lowered or (
        "prospekt" in lowered
        and any(k in lowered for k in ("blättern", "blätter", "viewer", "pdf", "zoom"))
    ):
        return {
            "retailer_id": retailer_id,
            "supports_structured_offers": False,
            "source_type": "leaflet_viewer_only",
            "observations_found": 0,
            "reason": (
                "Digital leaflet viewer / catalog reader without individual HTML product elements"
            ),
        }

    return {
        "retailer_id": retailer_id,
        "supports_structured_offers": False,
        "source_type": "unsupported_format",
        "observations_found": 0,
        "reason": "Generic landing page or unstructured brochure presentation",
    }


def fetch_and_parse_norma(
    client: httpx.Client | None = None,
    price_date: str | None = None,
    max_subpages: int = 5,
) -> list[dict]:
    """Fetches and parses current NORMA public offer pages with polite bounds."""
    should_close = False
    if client is None:
        client = httpx.Client(
            timeout=12.0,
            headers={"User-Agent": ("PriceWatch/0.1 (public product comparison)")},
            follow_redirects=True,
        )
        should_close = True

    all_offers = []
    seen_ids = set()

    try:
        resp = client.get(DEFAULT_NORMA_URL)
        resp.raise_for_status()
        main_html = resp.text
        offers = parse_norma_html(main_html, base_url=DEFAULT_NORMA_URL, price_date=price_date)
        for o in offers:
            pid = o["source_product_id"]
            if pid not in seen_ids:
                seen_ids.add(pid)
                all_offers.append(o)

        # Locate linked offer subpages (e.g. /de/angebote/ab-freitag.../)
        soup = BeautifulSoup(main_html, "html.parser")
        subpage_urls = set()
        for a in soup.find_all("a", href=True):
            link = a["href"].strip()
            if "/de/angebote/ab-" in link:
                full = urljoin(DEFAULT_NORMA_URL, link)
                if full != DEFAULT_NORMA_URL:
                    subpage_urls.add(full)

        for sub_url in sorted(subpage_urls)[:max_subpages]:
            try:
                sub_resp = client.get(sub_url)
                sub_resp.raise_for_status()
                sub_offers = parse_norma_html(
                    sub_resp.text, base_url=sub_url, price_date=price_date
                )
                for o in sub_offers:
                    pid = o["source_product_id"]
                    if pid not in seen_ids:
                        seen_ids.add(pid)
                        all_offers.append(o)
            except httpx.HTTPError:
                continue
    finally:
        if should_close:
            client.close()

    return all_offers


def seed_catalog_if_gtin(db: Database, observations_list: list[dict]) -> int:
    """Seeds the product identity catalog only when explicit GTINs exist."""
    repo = ProductRepository(db)
    items = []
    for obs in observations_list:
        ean = obs.get("ean")
        if ean and valid_ean(ean):
            try:
                items.append(
                    ProductInput(
                        ean=ean,
                        name=obs["name"][:300],
                        brand=(obs.get("brand")[:300] if obs.get("brand") else None),
                        package_label=(
                            obs.get("package_label")[:300] if obs.get("package_label") else None
                        ),
                        countries=["de"],
                        source_url=obs["source_url"],
                        categories=[],
                    )
                )
            except Exception:
                continue
    if items:
        return repo.upsert(items, source="retailer_observation")
    return 0


def parse_rossmann_capture_price(text):
    match = re.search(r"Aktueller Artikelpreis:\s*(\d+),(\d{2})\s*€", text or "")
    match = match or re.search(r"(?:Artikelpreis|Price)\s+(\d+),(\d{2})\s*€", text or "")
    return int(match[1]) * 100 + int(match[2]) if match else None
