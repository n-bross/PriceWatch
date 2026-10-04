"""Resumable imports of public GLOBUS catalogue and Combi product pages."""

import argparse
import fcntl
import json
import os
import re
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup

from .barcodes import valid_ean
from .catalog import ProductInput, ProductRepository
from .database import Database
from .observations import ObservationRepository, cents

GLOBUS = "https://produkte.globus.de/"
COMBI = "https://www.combi.de/"
EXCLUDE = {
    "restaurant",
    "vorbestellservice",
    "online-service",
    "wir-bei-globus",
    "globus-gruppe",
    "mobiles-menue",
    "gutschein-agb",
    "b2b-gutschein-agb",
    "angebote-der-woche",
    "geschenkgutscheine",
}


def today():
    return datetime.now(ZoneInfo("Europe/Berlin")).date().isoformat()


def globus_categories(html):
    soup = BeautifulSoup(html, "html.parser")
    urls = []
    for link in soup.select("a[href]"):
        url = urljoin(GLOBUS, link["href"])
        p = urlparse(url)
        segments = [x for x in p.path.split("/") if x]
        if (
            p.netloc == "produkte.globus.de"
            and len(segments) == 1
            and p.path.endswith("/")
            and segments[0] not in EXCLUDE
            and not p.query
        ):
            if url not in urls:
                urls.append(url)
    return urls


def parse_globus(html, url, price_date=None):
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for card in soup.select(".product-box[data-product-information]"):
        link = card.select_one(".product-name[href]")
        amount = card.select_one(".js-unit-price")
        if not link or not amount:
            continue
        try:
            meta = json.loads(card["data-product-information"])
            price = cents(
                amount.get("data-value") or amount.get_text(strip=True).replace("€", "").strip()
            )
        except (ValueError, TypeError, KeyError, ArithmeticError):
            continue
        product_url = urljoin(url, link["href"])
        if urlparse(product_url).netloc != "produkte.globus.de" or not meta.get("id"):
            continue
        gtin = card.select_one("[data-product-gtin]")
        code = gtin.get("data-product-gtin", "") if gtin else ""
        brand = card.select_one(".product-manufacturer")
        package = card.select_one(".product-price-unit")
        price_wrapper = card.select_one(".product-price-wrapper")
        qualifier = (
            "from"
            if re.search(
                r"\bab\b", price_wrapper.get_text(" ", strip=True) if price_wrapper else "", re.I
            )
            else None
        )
        rows.append(
            dict(
                source="globus_website",
                retailer="GLOBUS",
                source_product_id=meta["id"],
                name=link.get_text(" ", strip=True),
                ean=code if valid_ean(code) else None,
                price_cents=price,
                price_date=price_date or today(),
                scope="unknown",
                kind="unknown",
                channel="catalogue",
                source_url=product_url,
                price_qualifier=qualifier,
                brand=brand.get_text(" ", strip=True) if brand else None,
                package_label=package.get_text(" ", strip=True)[:300] if package else None,
                conditions_text=(
                    "Öffentlicher Katalogpreis; Preis und Verfügbarkeit abhängig "
                    "von der Markthalle. Keine bestätigte Filiale."
                ),
            )
        )
    pages = max(
        [
            int(x.get("value"))
            for x in soup.select(".pagination input[name=p]")
            if str(x.get("value", "")).isdigit()
        ]
        + [1]
    )
    return rows, pages


def json_objects(value):
    if isinstance(value, list):
        for item in value:
            yield from json_objects(item)
    elif isinstance(value, dict):
        yield value
        yield from json_objects(value.get("@graph", []))


def parse_combi(html, url, price_date=None):
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            objects = list(json_objects(json.loads(script.get_text())))
        except ValueError:
            continue
        for item in objects:
            if item.get("@type") != "Product" or not item.get("sku") or not item.get("name"):
                continue
            offers = item.get("offers") or []
            if isinstance(offers, dict):
                offers = [offers]
            for offer in offers:
                if not isinstance(offer, dict):
                    continue
                availability = offer.get("availability", "")
                if availability and availability.rsplit("/", 1)[-1] != "InStock":
                    continue
                spec = offer.get("priceSpecification") or {}
                if not isinstance(spec, dict):
                    continue
                amount = offer.get("price", spec.get("price"))
                currency = offer.get("priceCurrency", spec.get("priceCurrency"))
                if amount is None or currency != "EUR":
                    continue
                try:
                    price = cents(amount)
                except (ValueError, ArithmeticError):
                    continue
                code = str(
                    next(
                        (item[k] for k in ("gtin", "gtin13", "gtin8", "gtin14") if item.get(k)), ""
                    )
                )
                brand = item.get("brand") or item.get("manufacturer") or ""
                if isinstance(brand, dict):
                    brand = brand.get("name", "")
                rows.append(
                    dict(
                        source="combi_website",
                        retailer="Combi",
                        source_product_id=str(item["sku"]),
                        name=item["name"],
                        ean=code if valid_ean(code) else None,
                        price_cents=price,
                        price_date=price_date or today(),
                        scope="online",
                        kind="unknown",
                        channel="online",
                        source_url=url,
                        brand=brand or None,
                        conditions_text=(
                            "Onlineshoppreis, zzgl. Versand; kein bestätigter Filialpreis."
                        ),
                    )
                )
                break
    return rows


def checkpoint(path, state):
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(state, ensure_ascii=False))
    temp.replace(path)


class RateLimited(Exception):
    def __init__(self, retry_after):
        self.retry_after = retry_after


def fetch(client, url):
    for attempt in range(3):
        try:
            response = client.get(url)
            if response.status_code == 429:
                value = response.headers.get("Retry-After", "300")
                raise RateLimited(max(60, min(86400, int(value) if value.isdigit() else 300)))
            if response.status_code >= 500 and attempt < 2:
                time.sleep(2**attempt)
                continue
            response.raise_for_status()
            return response.text, today()
        except httpx.TransportError:
            if attempt == 2:
                raise
            time.sleep(2**attempt)
    raise RuntimeError("Retries exhausted")


def run(
    source,
    max_pages=100,
    workers=3,
    delay=0.3,
    state_dir="data/expansion",
    reset=False,
    refresh_hours=24,
):
    directory = Path(state_dir)
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / f"{source}-bulk.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        path = directory / f"{source}-bulk.json"
        state = json.loads(path.read_text()) if path.exists() else None
        if state and state.get("retry_after_epoch", 0) > time.time():
            print(json.dumps({"status": "cooldown", "source": source}), flush=True)
            return state
        if reset:
            state = None
        if state and state.get("complete"):
            completed_at = state.get("completed_at_epoch", 0)
            if time.time() < completed_at + refresh_hours * 3600:
                print(json.dumps({"status": "not_due", "source": source}), flush=True)
                return state
            state = None
        with httpx.Client(
            timeout=30,
            follow_redirects=True,
            headers={"User-Agent": "PriceWatch/1.0 (public price catalogue research)"},
        ) as client:
            if state and state.get("retry_after_epoch", 0) > time.time():
                print(
                    json.dumps(
                        {"status": "cooldown", "retry_after_epoch": state["retry_after_epoch"]}
                    ),
                    flush=True,
                )
                return state
            if state is None or state.get("discovery_pending"):
                try:
                    html, _ = fetch(
                        client,
                        GLOBUS
                        if source == "globus"
                        else COMBI + "sitemaps/combi/sitemap.produkte.xml",
                    )
                except RateLimited as error:
                    checkpoint(
                        path,
                        {
                            "retry_after_epoch": time.time() + error.retry_after,
                            "discovery_pending": True,
                        },
                    )
                    return {"status": "cooldown"}
                if source == "globus":
                    urls = globus_categories(html)
                else:
                    urls = [
                        x.text
                        for x in ET.fromstring(html).iter()
                        if x.tag.endswith("}loc")
                        and x.text
                        and urlparse(x.text).netloc == "www.combi.de"
                        and urlparse(x.text).path.endswith(".html")
                    ]
                if not urls:
                    raise ValueError("Discovery returned no catalogue URLs")
                state = {
                    "cycle_started_at_epoch": time.time(),
                    "pending": list(dict.fromkeys(urls)),
                    "completed": [],
                    "products": [],
                    "errors": {},
                    "rows_saved": 0,
                }
                checkpoint(path, state)
            database = Database(os.environ["DATABASE_URL"])
            observations = ObservationRepository(database)
            catalog = ProductRepository(database)
            seen = set(state["products"])
            completed = set(state["completed"])
            processed = 0
            failures = []
            with ThreadPoolExecutor(max_workers=workers) as pool:
                while state["pending"] and processed < max_pages:
                    batch = state["pending"][: min(workers, max_pages - processed)]
                    futures = [(url, pool.submit(fetch, client, url)) for url in batch]
                    stop = False
                    for url, future in futures:
                        processed += 1
                        try:
                            html, date = future.result()
                            if source == "globus":
                                rows, pages = parse_globus(html, url, date)
                                if not urlparse(url).query:
                                    for page in range(2, pages + 1):
                                        new = url + "?p=" + str(page)
                                        if new not in completed and new not in state["pending"]:
                                            state["pending"].append(new)
                            else:
                                rows = parse_combi(html, url, date)
                            unique = []
                            for row in rows:
                                key = row["source_product_id"]
                                if key not in seen:
                                    unique.append(row)
                            observations.save(unique)
                            catalog.upsert(
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
                                    for x in unique
                                    if x.get("ean")
                                ],
                                source="retailer_observation",
                            )
                            seen.update(x["source_product_id"] for x in unique)
                            completed.add(url)
                            state["rows_saved"] += len(unique)
                            state["errors"].pop(url, None)
                        except RateLimited as error:
                            state["retry_after_epoch"] = time.time() + error.retry_after
                            failures.append(url)
                            stop = True
                        except Exception as error:
                            state["errors"][url] = f"{type(error).__name__}: {str(error)[:200]}"
                            attempts = state.setdefault("error_attempts", {})
                            attempts[url] = attempts.get(url, 0) + 1
                            # Broken/removed URLs must not block refreshing healthy pages forever.
                            if attempts[url] < 3:
                                failures.append(url)
                        state["pending"].remove(url)
                    state["completed"] = sorted(completed)
                    state["products"] = sorted(seen)
                    checkpoint(path, {**state, "pending": state["pending"] + failures})
                    print(
                        json.dumps(
                            {
                                "source": source,
                                "pages_this_run": processed,
                                "pages_total": len(completed),
                                "unique_products": len(seen),
                                "pending": len(state["pending"]) + len(failures),
                                "errors": len(state["errors"]),
                            }
                        ),
                        flush=True,
                    )
                    if stop:
                        break
                    time.sleep(delay)
            state["pending"].extend(failures)
            state["complete"] = not state["pending"]
            if state["complete"]:
                state["completed_at_epoch"] = time.time()
            state["updated_at"] = datetime.now(ZoneInfo("Europe/Berlin")).isoformat()
            checkpoint(path, state)
            return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=["globus", "combi"], required=True)
    parser.add_argument("--max-pages", type=int, default=100)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--delay", type=float, default=0.3)
    parser.add_argument("--state-dir", default="data/expansion")
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--refresh-hours", type=float, default=24)
    args = parser.parse_args()
    if (
        not 1 <= args.workers <= 4
        or args.max_pages < 1
        or args.delay < 0.2
        or args.refresh_hours <= 0
    ):
        parser.error("workers 1–4, max-pages >=1, delay >=0.2 required")
    run(**vars(args))
