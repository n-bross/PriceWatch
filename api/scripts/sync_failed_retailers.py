"""Refresh recovered public offer feeds with explicit dates and source evidence."""

import fcntl
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

from pricewatch_api.conditional_fetch import ConditionalFetcher, SourceCooldown, atomic_json
from pricewatch_api.database import Database
from pricewatch_api.failed_retailers import (
    parse_alnatura,
    parse_bio_company,
    parse_denns,
    parse_netto_dog,
)
from pricewatch_api.observations import ObservationRepository

BIO = "https://www.biocompany.de/neuigkeiten/"
SOURCES = (
    [
        ("bio_company", BIO + slug, parse_bio_company, [region])
        for slug, region in [
            ("angebote.html", "Berlin/Brandenburg; Filialverfügbarkeit nicht bestätigt"),
            ("angebote-dresden.html", "Dresden; Filialverfügbarkeit nicht bestätigt"),
            ("aktuelle-angebote-in-mecklenbug-vorpommern.html", "Mecklenburg-Vorpommern"),
            (
                "angebote-naturkosmetik.html",
                "Naturkosmetik in allen BIO COMPANY Märkten laut Seite",
            ),
        ]
    ]
    + [
        ("denns", "https://www.biomarkt.de/page-data/angebote/page-data.json", parse_denns, []),
        ("alnatura", "https://www.alnatura.de/angebote", parse_alnatura, []),
        ("alnatura", "https://www.alnatura.de/maerkte/angebote-vorschau", parse_alnatura, []),
        ("netto_dog", "https://netto.de/prospekte/", parse_netto_dog, []),
    ]
    + [
        ("netto_dog", f"https://netto.de/angebote/{slug}/", parse_netto_dog, [])
        for slug in [
            "spar-stars",
            "regionale-produkte",
            "ost-lieblinge",
            "hammer-mittwoch",
            "knaller-wochenende",
            "nonfood",
            "dauerhaft-reduziert",
        ]
    ]
)


def main():
    directory = Path("data/expansion")
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "recovered-sources.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('{"status":"locked"}', flush=True)
            return []
        return sync(directory)


def sync(directory):
    fetcher = ConditionalFetcher(directory / "recovered-http-cache")
    repo = ObservationRepository(Database(os.environ["DATABASE_URL"]))
    results = []
    with httpx.Client(
        timeout=40,
        follow_redirects=True,
        headers={"User-Agent": "PriceWatch/0.1 (public price catalog)"},
    ) as client:
        for index, (retailer, url, parser, args) in enumerate(SOURCES):
            result = {
                "retailer": retailer,
                "url": url,
                "attempted_at": datetime.now(ZoneInfo("Europe/Berlin")).isoformat(),
            }
            try:
                body, status = fetcher.fetch(client, url)
                result["http_status"] = status
                today = datetime.now(ZoneInfo("Europe/Berlin")).date().isoformat()
                rows = parser(body, url, today, *args)
                (directory / f"recovered-{index}.html").write_text(body)
                if retailer == "denns":
                    for row in rows:
                        row["source_url"] = "https://www.biomarkt.de/angebote"
                        row["data_url"] = url
                        row["conditions_text"] = (
                            "Teilnehmende Denns/BioMarkt-Märkte; keine bestätigte lokale Filiale. "
                            + (row.get("conditions_text") or "")
                        )
                count = repo.save(rows)
                result.update(
                    parsed=count,
                    current=sum(
                        (not x.get("valid_from") or x["valid_from"] <= today)
                        and (not x.get("valid_until") or x["valid_until"] >= today)
                        for x in rows
                    ),
                    ean_count=sum(bool(x.get("ean")) for x in rows),
                    status="imported" if rows else "no_unambiguous_prices",
                )
            except (httpx.HTTPError, SourceCooldown, ValueError, KeyError) as exc:
                result.update(status="failed", reason=f"{type(exc).__name__}: {str(exc)[:200]}")
            results.append(result)
            print(json.dumps(result, ensure_ascii=False), flush=True)
            atomic_json(directory / "recovered-sources-status.json", results)
            time.sleep(0.5)
    return results


if __name__ == "__main__":
    sys.exit(1 if any(x["status"] == "failed" for x in main()) else 0)
