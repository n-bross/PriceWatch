"""Bounded, resumable ROSSMANN public online price capture.

Only freshly rendered pages are imported; old audit captures are never replayed.
Playwright is an optional dependency (``uv sync --extra browser``).
"""

import argparse
import fcntl
import json
import os
import re
import time
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from .database import Database
from .observations import ObservationRepository
from .retailer_sources import parse_rossmann_capture_price

START_URL = "https://www.rossmann.de/de/angebote/m/angebote"
EXPRESSION = r"""() => ({
  url: location.href,
  observed_at: new Date().toISOString(),
  dateText: document.body?.innerText.match(/Gültig ab Montag:[^\n]+/)?.[0],
  cards: [...(document.querySelector('[data-testid="search-products"]')?.querySelectorAll(
    '[data-testid="product-card"]') || [])].map(c => ({
    badges: [...c.querySelectorAll('[data-testid="product-disruptor"]')]
      .map(b => b.innerText.trim()),
    dateText: c.innerText.match(/Gültig ab Montag:[^\n]+/)?.[0],
    name: c.querySelector('[data-testid="product-brandAndName"]')?.innerText,
    package_label: c.querySelector('[data-testid="product-baseprice"]')?.innerText,
    priceText: c.querySelector('[data-testid="product-price"]')?.textContent,
    source_url: c.querySelector('a[href*="/p/"]')?.href
  })),
  next: document.querySelector('a[aria-label="Nächste Seite"]')?.href || null
})"""


def allowed_listing(url):
    p = urlparse(url)
    return p.scheme == "https" and p.netloc == "www.rossmann.de" and p.path == urlparse(
        START_URL
    ).path


def campaign_dates(text):
    match = re.fullmatch(
        r"Gültig ab Montag:\s*(\d{2})\.(\d{2})\.\s*-\s*(\d{2})\.(\d{2})\.(\d{4})",
        text or "",
    )
    if not match:
        raise ValueError("Missing explicit ROSSMANN campaign dates")
    day1, month1, day2, month2, year = map(int, match.groups())
    # The displayed end year also identifies a December-to-January start year.
    start = date(year - (month1 > month2), month1, day1)
    end = date(year, month2, day2)
    if not 0 <= (end - start).days <= 14:
        raise ValueError("Unexpected ROSSMANN campaign duration")
    return start, end


def parse_page(capture, observed_date):
    observed = date.fromisoformat(observed_date)
    if not allowed_listing(capture.get("url", "")):
        raise ValueError("Unexpected ROSSMANN listing URL")
    rows = {}
    for card in capture.get("cards", []):
        url = card.get("source_url") or ""
        parsed = urlparse(url)
        price = parse_rossmann_capture_price(card.get("priceText"))
        name = " ".join((card.get("name") or "").split())
        if (parsed.scheme != "https" or parsed.netloc != "www.rossmann.de"
                or "/p/" not in parsed.path or price is None or price <= 0 or not name):
            continue
        product_id = parsed.path.rsplit("/", 1)[-1]
        if not product_id:
            continue
        # Banner dates do not establish the validity of a card's purchase price.
        start = end = None
        if card.get("dateText"):
            start, end = campaign_dates(card["dateText"])
            if not start <= observed <= end:
                continue
        advertised = "Aus der Werbung" in (card.get("badges") or []) or start is not None
        rows[product_id] = dict(
            source="rossmann_browser", retailer="ROSSMANN", source_product_id=product_id,
            name=name, ean=None, listed_offer=advertised, price_cents=price,
            price_date=observed_date, scope="online", kind="offer" if advertised else "unknown",
            source_url=url,
            valid_from=start.isoformat() if start else None,
            valid_until=end.isoformat() if end else None,
            package_label=card.get("package_label"),
            conditions_text="Öffentlich beobachteter Onlinepreis; Filialpreis und Verfügbarkeit "
                            "nicht bestätigt.",
        )
    if not rows:
        raise ValueError("No verifiable public price cards; challenge or layout change")
    next_url = capture.get("next")
    if next_url and (not allowed_listing(next_url) or next_url == capture["url"]):
        raise ValueError("Unsafe or non-advancing ROSSMANN pagination")
    return list(rows.values()), next_url


def capture_rows(capture):
    """Import saved evidence using its observation time, never the import day."""
    try:
        observed = datetime.fromisoformat(capture.get("observed_at") or "")
        if observed.tzinfo is None:
            raise ValueError("Missing timezone")
    except (TypeError, ValueError) as exc:
        raise ValueError("Missing or invalid explicit observation timestamp") from exc
    observed_date = observed.astimezone(ZoneInfo("Europe/Berlin")).date().isoformat()
    return parse_page(capture, observed_date)[0]


class Browser:
    """Fresh isolated context; never attaches to a user's authenticated browser."""

    def __init__(self, executable):
        self.executable = executable

    def __enter__(self):
        from playwright.sync_api import sync_playwright
        self.playwright = sync_playwright().start()
        try:
            self.browser = self.playwright.chromium.launch(
                executable_path=self.executable, headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"], timeout=30000,
            )
            self.page = self.browser.new_page()
            return self
        except Exception:
            self.playwright.stop()
            raise

    def __exit__(self, *args):
        try:
            self.browser.close()
        finally:
            self.playwright.stop()

    def fetch(self, url):
        if not allowed_listing(url):
            raise ValueError("Invalid listing URL")
        response = self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
        try:
            self.page.wait_for_selector(
                '[data-testid="search-products"] [data-testid="product-card"]', timeout=20000
            )
        except Exception as exc:
            status = response.status if response else "unknown"
            raise ValueError(
                f"No public product cards: HTTP {status}; title={self.page.title()!r}; "
                "challenge or layout change; no bypass attempted"
            ) from exc
        return self.page.evaluate(EXPRESSION)


def write_state(path, state):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2))
    temporary.replace(path)


def run(repository, state_path, fetch, max_pages=3, now=None, observed_date=None):
    """Checkpoint after successful database writes; replay after a crash is idempotent."""
    if not 1 <= max_pages <= 20:
        raise ValueError("max_pages must be between 1 and 20")
    now = time.time() if now is None else now
    observed_date = observed_date or datetime.now(ZoneInfo("Europe/Berlin")).date().isoformat()
    state_path = Path(state_path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    with state_path.with_suffix(".lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {"status": "locked", "rows": 0}
        state = json.loads(state_path.read_text()) if state_path.exists() else {}
        if state.get("next_due", 0) > now:
            return {"status": "cooldown", "rows": 0, "next_due": state["next_due"]}
        # Re-read page one after date rollover so a campaign change cannot be skipped.
        if state.get("date") != observed_date:
            state = {}
        total = 0
        try:
            for _ in range(max_pages):
                url = state.get("next") or START_URL
                if not allowed_listing(url):
                    raise ValueError("Invalid saved listing URL")
                capture = fetch(url)
                if capture.get("url") != url:
                    raise ValueError("Unexpected listing redirect")
                rows, next_url = parse_page(capture, observed_date)
                if state.get("campaign") and state["campaign"] != capture.get("dateText"):
                    state = {}
                    raise ValueError("Campaign changed mid-cycle; restarting after cooldown")
                seen = state.get("pages", [])
                if url in seen or next_url in seen:
                    raise ValueError("Pagination cycle detected")
                repository.save(rows)
                total += len(rows)
                state.update(
                    next=next_url, date=observed_date, campaign=capture.get("dateText"),
                    pages=seen + [url], last_success=now, status="running", error=None,
                    next_due=0,
                )
                if not next_url:
                    state.update(status="complete", next_due=now + 6 * 3600, pages=[])
                write_state(state_path, state)
                if not next_url:
                    break
        except Exception as exc:
            state.update(status="blocked", error=f"{type(exc).__name__}: {exc}"[:800],
                         next_due=now + 6 * 3600)
            write_state(state_path, state)
        return {"status": state["status"], "rows": total, "error": state.get("error"),
                "next_due": state.get("next_due", 0)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", default="data/rossmann-recurring/state.json")
    parser.add_argument("--max-pages", type=int, default=3)
    parser.add_argument("--browser", default="/usr/bin/google-chrome")
    args = parser.parse_args()
    db = Database(os.environ["DATABASE_URL"])
    db.initialize()
    # Start the browser lazily, after lock/cooldown checks have passed.
    from contextlib import ExitStack
    with ExitStack() as stack:
        browser = None

        def fetch(url):
            nonlocal browser
            if browser is None:
                browser = stack.enter_context(Browser(args.browser))
            return browser.fetch(url)

        result = run(ObservationRepository(db), args.state, fetch, args.max_pages)
        print(json.dumps(result, ensure_ascii=False))
        if result["status"] == "blocked":
            raise SystemExit(1)


if __name__ == "__main__":
    main()
