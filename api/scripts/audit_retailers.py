"""Bounded, reproducible public HTTP/JSON-LD/PDF checks. No anti-bot bypass."""

import hashlib
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin

import httpx
import pymupdf
from bs4 import BeautifulSoup

from pricewatch_api.barcodes import valid_ean
from pricewatch_api.catalog import ProductInput, ProductRepository
from pricewatch_api.database import Database
from pricewatch_api.observations import ObservationRepository, cents

ROOT = Path(__file__).resolve().parents[1]
DIRECTORY = ROOT / "data" / "retailer-audit"
DIRECTORY.mkdir(parents=True, exist_ok=True)
RETAILERS = json.loads((ROOT / "pricewatch_api" / "retailers.json").read_text())


def extract_jsonld(soup, url, retailer):
    result = []

    def walk(obj):
        if not isinstance(obj, dict):
            if isinstance(obj, list):
                for value in obj:
                    walk(value)
            return
        types = obj.get("@type")
        types = types if isinstance(types, list) else [types]
        if "Product" in types and obj.get("name"):
            offers = obj.get("offers", [])
            offers = offers if isinstance(offers, list) else [offers]
            for offer in offers:
                if (
                    not isinstance(offer, dict)
                    or offer.get("priceCurrency") != "EUR"
                    or offer.get("price") is None
                ):
                    continue
                try:
                    price = cents(offer["price"])
                except (ValueError, ArithmeticError):
                    continue
                code = next(
                    (
                        str(obj.get(k))
                        for k in ["gtin13", "gtin8", "gtin14", "gtin"]
                        if valid_ean(str(obj.get(k, "")))
                    ),
                    None,
                )
                source = urljoin(url, offer.get("url") or obj.get("url") or url)
                if not source.startswith("https://"):
                    continue
                result.append(
                    dict(
                        source="retailer_website",
                        retailer=retailer,
                        name=str(obj["name"])[:300],
                        ean=code,
                        price_cents=price,
                        price_date=datetime.now(UTC).date().isoformat(),
                        scope="unknown",
                        kind="unknown",
                        source_product_id=str(obj.get("sku") or obj.get("productID") or source),
                        source_url=source,
                        brand=obj.get("brand")
                        if isinstance(obj.get("brand"), str)
                        else (obj.get("brand") or {}).get("name"),
                        package_label=None,
                    )
                )
        for value in obj.values():
            if isinstance(value, (dict, list)):
                walk(value)

    for script in soup.select('script[type="application/ld+json"]'):
        try:
            walk(json.loads(script.get_text()))
        except (ValueError, TypeError):
            pass
    return result


def audit(retailer):
    attempts = []
    entries = []
    pdfs = []
    with httpx.Client(
        timeout=20,
        follow_redirects=True,
        headers={"User-Agent": "PriceWatch/0.1 (public price research)"},
    ) as c:
        for number, url in enumerate(retailer["urls"]):
            try:
                r = c.get(url)
                soup = BeautifulSoup(r.text, "html.parser")
                title = soup.title.get_text(" ", strip=True) if soup.title else ""
                attempt = {
                    "method": (
                        ["official_offers_page", "alternative_shop_or_leaflet", "official_site"][
                            number
                        ]
                        if number < 3
                        else "additional_discovered_path"
                    ),
                    "url": url,
                    "final_url": str(r.url),
                    "http_status": r.status_code,
                    "title": title,
                    "structured_prices": 0,
                }
                if r.status_code == 200:
                    (DIRECTORY / f"{retailer['id']}-{number}.html").write_text(r.text)
                    found = extract_jsonld(soup, str(r.url), retailer["name"])
                    entries.extend(found)
                    attempt["structured_prices"] = len(found)
                    links = []
                    for a in soup.select("a[href]"):
                        href = urljoin(str(r.url), a["href"])
                        label = a.get_text(" ", strip=True)
                        if ".pdf" in href.lower() and re.search(
                            r"angebot|prospekt|flyer|handzettel|\bkw\b", href + " " + label, re.I
                        ):
                            links.append(href)
                    attempt["pdf_candidates"] = list(dict.fromkeys(links))[:8]
                    for pdf_url in attempt["pdf_candidates"][:2]:
                        try:
                            with c.stream("GET", pdf_url) as download:
                                download.raise_for_status()
                                content = bytearray()
                                for chunk in download.iter_bytes(1024 * 1024):
                                    content.extend(chunk)
                                    if len(content) > 80 * 1024 * 1024:
                                        raise ValueError("PDF exceeds 80 MiB")
                            if not content.startswith(b"%PDF"):
                                raise ValueError("Response is not PDF")
                            digest = hashlib.sha256(content).hexdigest()
                            (DIRECTORY / f"{digest}.pdf").write_bytes(content)
                            doc = pymupdf.open(stream=bytes(content), filetype="pdf")
                            text = "\n".join(page.get_text() for page in doc)
                            (DIRECTORY / f"{digest}.txt").write_text(text)
                            pdfs.append(
                                {
                                    "url": pdf_url,
                                    "sha256": digest,
                                    "bytes": len(content),
                                    "pages": len(doc),
                                    "price_mentions": len(re.findall(r"\d+[,.]\d{2}\s*€", text)),
                                    "price_assignments_verified": False,
                                }
                            )
                        except Exception as exc:
                            attempt.setdefault("pdf_errors", []).append(
                                {"url": pdf_url, "error": str(exc)[:200]}
                            )
                    attempt["reason"] = (
                        "Structured product prices extracted"
                        if found
                        else (
                            "Page accessible; no unambiguous Product/Offer EUR prices in "
                            "JSON-LD. Regional selection or a site-specific renderer may be "
                            "required."
                        )
                    )
                else:
                    marker = next(
                        (
                            t
                            for t in [
                                "Access Denied",
                                "Forbidden",
                                "captcha",
                                "Challenge",
                                "Just a moment",
                                "Bad Gateway",
                            ]
                            if t.lower() in r.text.lower()
                        ),
                        None,
                    )
                    attempt["reason"] = f"HTTP {r.status_code}" + (
                        f"; page marker: {marker}" if marker else ""
                    )
                attempts.append(attempt)
            except Exception as exc:
                attempts.append(
                    {
                        "method": (
                            [
                                "official_offers_page",
                                "alternative_shop_or_leaflet",
                                "official_site",
                            ][number]
                            if number < 3
                            else "additional_discovered_path"
                        ),
                        "url": url,
                        "error": str(exc)[:250],
                        "reason": "Network/timeout failure",
                    }
                )
    return {
        **retailer,
        "checked_at": datetime.now(UTC).isoformat(),
        "full_price_list_downloaded": False,
        "attempts": attempts,
        "downloaded_pdfs": pdfs,
        "website_prices": len(entries),
    }, entries


if __name__ == "__main__":
    db = Database(os.environ["DATABASE_URL"])
    repo = ObservationRepository(db)
    results = []
    with ThreadPoolExecutor(max_workers=5) as pool:
        jobs = {pool.submit(audit, r): r for r in RETAILERS}
        for future in as_completed(jobs):
            result, entries = future.result()
            repo.save(entries)
            products = [
                ProductInput(
                    ean=e["ean"],
                    name=e["name"],
                    brand=e["brand"],
                    countries=["en:germany"],
                    reported_stores=e["retailer"],
                    source_url=e["source_url"],
                )
                for e in entries
                if e["ean"]
            ]
            ProductRepository(db).upsert(products, source="retailer_observation")
            results.append(result)
            (DIRECTORY / "http-audit.json").write_text(
                json.dumps(sorted(results, key=lambda x: x["name"]), ensure_ascii=False, indent=2)
            )
            print(
                result["id"],
                len(result["attempts"]),
                "probes",
                len(entries),
                "prices",
                len(result["downloaded_pdfs"]),
                "PDFs",
                flush=True,
            )
