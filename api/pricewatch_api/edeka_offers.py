"""Explicit EDEKA advertised offers, with source dates and separate app prices."""

import re
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from .models import PriceInput

URL = "https://www.edeka.de/angebote/"
PRICE = re.compile(r"(App Preis|Rabattierter Preis|Festpreis) von (\d+[.,]\d{2})€(?: \(.*\))?")
PERIOD = re.compile(r"Gültig vom (\d{2}\.\d{2}\.\d{4}) bis zum (\d{2}\.\d{2}\.\d{4})")


def parse_html(body: str, observed_at: datetime) -> tuple[list[PriceInput], list[dict]]:
    soup = BeautifulSoup(body, "html.parser")
    periods = set(PERIOD.findall(soup.get_text(" ", strip=True)))
    if len(periods) != 1:
        raise ValueError("EDEKA page needs one explicit, unambiguous validity period")
    first, last = next(iter(periods))
    start, end = (datetime.strptime(x, "%d.%m.%Y").date() for x in (first, last))
    if not 0 <= (end - start).days <= 14:
        raise ValueError("Unexpected EDEKA weekly validity period")
    cards = []
    for dialog in soup.select('dialog[id^="dialog-angebot-"]'):
        heading = dialog.find("h3")
        if not heading:
            raise ValueError("EDEKA offer dialog missing heading")
        description = dialog.select_one("p.line-clmap-2, p.line-clamp-2")
        terms = dialog.select_one(".autoformat")
        starts = re.findall(r"\bab (\d{2}\.\d{2}\.)", dialog.get_text(" ", strip=True))
        if len(set(starts)) > 1:
            raise ValueError("Ambiguous EDEKA offer start")
        cards.append(
            dict(
                id=dialog["id"],
                name=heading.get_text(" ", strip=True).removeprefix("Angebot:").strip(),
                description=description.get_text(" ", strip=True) if description else None,
                terms=terms.get_text(" ", strip=True) if terms else "",
                prices=[s.get_text(" ", strip=True) for s in dialog.select("span.sr-only")],
                start="ab " + starts[0] if starts else None,
            )
        )
    if not cards:
        raise ValueError("No EDEKA offer dialogs; possible challenge or markup change")
    return parse_capture(
        dict(products=cards, valid_from=start.isoformat(), valid_until=end.isoformat()), observed_at
    )


def parse_capture(data: dict, observed_at: datetime) -> tuple[list[PriceInput], list[dict]]:
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("EDEKA capture timestamp needs a timezone")
    if data.get("source_url", URL) != URL:
        raise ValueError("Expected official EDEKA offers source URL")
    start = date.fromisoformat(data["valid_from"])
    end = date.fromisoformat(data["valid_until"])
    if "period_text" in data:
        matches = PERIOD.findall(data["period_text"])
        if len(matches) != 1 or tuple(
            datetime.strptime(value, "%d.%m.%Y").date() for value in matches[0]
        ) != (start, end):
            raise ValueError("EDEKA capture dates disagree with source period")
    if not 0 <= (end - start).days <= 14:
        raise ValueError("Unexpected EDEKA weekly validity period")
    prices, records = [], []
    seen = set()
    for card in data["products"]:
        card_start = start
        if card.get("start"):
            match = re.fullmatch(r"ab (\d{2})\.(\d{2})\.", card["start"])
            if not match:
                raise ValueError("Unrecognized EDEKA offer start")
            candidates = []
            for year in range(start.year, end.year + 1):
                candidate = date(year, int(match[2]), int(match[1]))
                if start <= candidate <= end:
                    candidates.append(candidate)
            if len(candidates) != 1:
                raise ValueError("EDEKA offer start outside advertised period")
            card_start = candidates[0]
        for label in card["prices"]:
            match = PRICE.fullmatch(label)
            if not match:
                continue  # PAYBACK points and crossed-out historical prices are not cash offers.
            app = match[1] == "App Preis"
            key = card["id"] + (":app" if app else "")
            if key in seen:
                raise ValueError("Duplicate or ambiguous EDEKA offer price")
            seen.add(key)
            conditions = "Nur in mit dieser Werbung gekennzeichneten, teilnehmenden Märkten"
            if app:
                conditions += (
                    "; EDEKA App, Registrierung und Lieblingsmarkt erforderlich; nicht Hessenring"
                )
            item = PriceInput(
                retailer="edeka",
                source_product_id=key,
                name=card["name"],
                price_cents=int(Decimal(match[2].replace(",", ".")) * 100),
                kind="offer",
                valid_from=card_start,
                valid_until=end,
                scope="chain_advertised",
                package_label=card.get("description"),
                source_url=URL + "#" + card["id"].removeprefix("dialog-"),
                observed_at=observed_at,
                requires_membership=app,
                conditions=conditions,
            )
            prices.append(item)
            # Day-level evidence avoids growing identical observations on each timer tick.
            record = item.model_dump(mode="json", exclude={"observed_at"})
            record.update(
                source="edeka_public_offers",
                retailer="EDEKA",
                price_date=observed_at.astimezone(ZoneInfo("Europe/Berlin")).date().isoformat(),
                conditions_text=card.get("terms", ""),
                region_label="Teilnehmende Märkte; keine bestätigte lokale Filiale",
            )
            records.append(record)
    if not prices:
        raise ValueError("No explicit EDEKA purchase prices")
    return prices, records
