"""Fetch all pages in GLOBUS/Combi's public offer listings and HIT website JSON."""

import json
import os
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin

import httpx
from audit_retailers import extract_jsonld
from bs4 import BeautifulSoup

from pricewatch_api.barcodes import valid_ean
from pricewatch_api.catalog import ProductInput, ProductRepository
from pricewatch_api.database import Database
from pricewatch_api.observations import ObservationRepository, cents

D = Database(os.environ["DATABASE_URL"])
observation_repo = ObservationRepository(D)
P = ProductRepository(D)
DIR = Path("data/retailer-audit")
now = datetime.now(UTC)


def save(rows):
    observation_repo.save(rows)
    P.upsert(
        [
            ProductInput(
                ean=x["ean"],
                name=x["name"][:300],
                brand=x.get("brand") or None,
                package_label=x.get("package_label") or None,
                countries=["en:germany"],
                reported_stores=x["retailer"],
                source_url=x["source_url"],
            )
            for x in rows
            if x.get("ean") and valid_ean(x["ean"])
        ],
        source="retailer_observation",
    )


def globus(c):
    base = "https://produkte.globus.de/angebote-der-woche/"
    count = 0
    seen = set()
    initial = c.get(base)
    initial.raise_for_status()
    soup = BeautifulSoup(initial.text, "html.parser")
    (DIR / "globus-0.html").write_text(initial.text)
    last = max(
        int(e["value"])
        for e in soup.select(".pagination input[name=p]")
        if str(e.get("value", "")).isdigit()
    )
    for page in range(1, last + 1):
        if page > 1:
            r = c.get(base, params={"p": page})
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            (DIR / f"globus-page-{page}.html").write_text(r.text)
        rows = []
        for card in soup.select(".product-box[data-product-information]"):
            link = card.select_one(".product-name[href]")
            amount = card.select_one(".js-unit-price")
            gtin = card.select_one("[data-product-gtin]")
            if not link or not amount:
                continue
            meta = json.loads(card["data-product-information"])
            identifier = meta["id"]
            if identifier in seen:
                continue
            seen.add(identifier)
            try:
                price = cents(amount.get_text(strip=True).replace("€", "").strip())
            except ValueError:
                continue
            code = gtin.get("data-product-gtin") if gtin else None
            rows.append(
                dict(
                    source="globus_website",
                    retailer="GLOBUS",
                    source_product_id=identifier,
                    name=link.get_text(" ", strip=True),
                    ean=code if code and valid_ean(code) else None,
                    price_cents=price,
                    price_date=now.date().isoformat(),
                    scope="unknown",
                    kind="unknown",
                    source_url=link["href"],
                    brand=card.select_one(".product-manufacturer").get_text(" ", strip=True)[:300]
                    if card.select_one(".product-manufacturer")
                    else None,
                    package_label=card.select_one(".product-price-unit").get_text(" ", strip=True)[
                        :300
                    ]
                    if card.select_one(".product-price-unit")
                    else None,
                    conditions_text=(
                        "Katalogpreis; Preise und Verfügbarkeiten können abweichen. "
                        "Keine bestätigte Markthalle."
                    ),
                )
            )
        save(rows)
        count += len(rows)
        print("globus", page, last, len(rows), count, flush=True)
        time.sleep(0.5)
    return {
        "listing_pages": last,
        "processed": count,
        "listing_complete": True,
        "full_assortment": False,
        "scope": "unknown",
    }


def combi(c):
    base = "https://www.combi.de/prospekt-angebote_220012750.html"
    initial = c.get(base)
    initial.raise_for_status()
    soup = BeautifulSoup(initial.text, "html.parser")
    (DIR / "combi-0.html").write_text(initial.text)
    pages = max(
        [int(m[1]) for a in soup.select("a[href]") if (m := re.search(r"\?page=(\d+)", a["href"]))]
        + [1]
    )
    seen = set()
    count = 0
    for page in range(1, pages + 1):
        if page > 1:
            r = c.get(base, params={"page": page})
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
        for card in soup.select(".product-card[data-listitemid]"):
            link = card.select_one("a.product-card__poster__link[href]")
            if not link:
                continue
            url = urljoin(base, link["href"])
            if url in seen:
                continue
            seen.add(url)
            r = c.get(url)
            r.raise_for_status()
            detail = BeautifulSoup(r.text, "html.parser")
            rows = extract_jsonld(detail, url, "Combi")
            for row in rows:
                row.update(
                    source="combi_website",
                    scope="online",
                    conditions_text="Onlineshoppreis, zzgl. Versand; kein bestätigter Filialpreis.",
                )
            save(rows)
            count += len(rows)
            time.sleep(0.3)
        print("combi", page, pages, count, flush=True)
    return {
        "listing_pages": pages,
        "processed": count,
        "listing_complete": True,
        "full_assortment": False,
        "scope": "online",
    }


def hit(c):
    rows = []
    seen = set()
    fresh = []
    registry = json.loads(Path("pricewatch_api/retailers.json").read_text())
    urls = next(r["urls"] for r in registry if r["id"] == "hit")
    for index, url in enumerate(urls[:2]):
        response = c.get(url)
        if response.is_success:
            file = DIR / f"hit-{index}.html"
            file.write_text(response.text)
            fresh.append(file)
    if not fresh:
        raise ValueError("HIT live pages unavailable; cached prices not re-dated")
    for file in fresh:
        soup = BeautifulSoup(file.read_text(), "html.parser")
        for node in soup.select("[data-leaflet]"):
            a = json.loads(node["data-leaflet"])
            if a["id"] in seen or a.get("price") is None:
                continue
            seen.add(a["id"])
            code = str(a.get("ean") or "")
            candidates = [
                x
                for x in a.get("assortmentMatnr", [])
                if x.get("MEINH") == "ST" and valid_ean(str(x.get("EAN11", "")))
            ]
            codes = set(x["EAN11"] for x in candidates)
            # Broader assortment lists are retained, never assigned as an exact product identity.
            code = code if valid_ean(code) else (next(iter(codes)) if len(codes) == 1 else None)
            for member, amount in [(False, a["price"]), (True, a.get("appPrice"))]:
                if amount is None:
                    continue
                rows.append(
                    dict(
                        source="hit_website",
                        retailer="HIT",
                        source_product_id=str(a["id"]) + (":app" if member else ""),
                        name=a["headline"].replace("\n", " ")[:300],
                        ean=code,
                        price_cents=cents(amount),
                        kind="offer",
                        scope="unknown",
                        price_date=now.date().isoformat(),
                        source_url=a["url"],
                        valid_from=a["validFrom"][:10],
                        valid_until=a["validTo"][:10],
                        requires_membership=member,
                        conditions_text="Nur mit HIT-App; Couponbedingungen beachten"
                        if member
                        else "Beworbenes Angebot; keine bestätigte Filiale",
                        package_label=a.get("overview", "").replace("\n", " ")[:300],
                        candidate_gtins=sorted(codes),
                    )
                )
    save(rows)
    return {"processed": len(rows), "full_assortment": False, "scope": "unknown"}


if __name__ == "__main__":
    result = {}
    with httpx.Client(
        timeout=30, follow_redirects=True, headers={"User-Agent": "PriceWatch/0.1"}
    ) as c:
        for name, fn in [
            ("hit", lambda: hit(c)),
            ("globus", lambda: globus(c)),
            ("combi", lambda: combi(c)),
        ]:
            try:
                result[name] = fn()
            except Exception as exc:
                result[name] = {"error": str(exc)[:300], "full_assortment": False}
                print(name, result[name], flush=True)
            (DIR / "catalog-crawl.json").write_text(json.dumps(result, indent=2))
