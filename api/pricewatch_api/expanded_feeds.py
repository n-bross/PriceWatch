"""myTime public full-assortment scraper and JSON-LD detail enricher."""

import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse
from zoneinfo import ZoneInfo

try:
    import fcntl
except ImportError:
    fcntl = None

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import delete, select

from .barcodes import valid_ean
from .catalog import ProductInput, ProductRepository
from .database import Database
from .observations import ObservationRepository, cents, observations, retry_delay

logger = logging.getLogger(__name__)

SOURCE_NAME = "mytime_website"
RETAILER_NAME = "myTime"
SCOPE = "online"
KIND = "unknown"
CURRENCY = "EUR"
BASE_URL = "https://www.mytime.de"
LISTING_URL_TEMPLATE = "https://www.mytime.de/lebensmittel-lieferservice?page={page}"
CONDITION_TEXT = "Onlinepreis zzgl. Versand; Mengenrabatte nicht eingerechnet"
DEFAULT_CHECKPOINT_PATH = Path("data/expansion/mytime-progress.json")
DEFAULT_INTERVAL_HOURS = 24.0


class LockError(Exception):
    """Raised when an overlapping sync process holds the lock."""

    pass


def get_berlin_today() -> str:
    return datetime.now(ZoneInfo("Europe/Berlin")).date().isoformat()


def extract_price_cents(text: str) -> int:
    if not text:
        raise ValueError("Empty price string")
    cleaned = text.replace("\xa0", " ").strip()
    match = re.search(r"(\d+[.,]\d{2})", cleaned)
    if not match:
        raise ValueError(f"No price pattern found in: {text!r}")
    amount = cents(match.group(1))
    if amount <= 0:
        raise ValueError("Non-positive price")
    return amount


def parse_listing_page(
    html_content: str, price_date: str | None = None
) -> tuple[list[dict], int | None]:
    """Parses a myTime listing HTML page.

    Never infers EAN from images, SKU, or barcodes.
    Only extracts current price, strictly avoiding tier/bulk/old prices.
    """
    soup = BeautifulSoup(html_content, "html.parser")
    cards = soup.select("#product-list-210000000 .product-card")
    if not cards:
        cards = soup.select(".product-card")

    observation_date = price_date or get_berlin_today()
    products = []

    for card in cards:
        # SKU from form[data-sku] or any card element with data-sku
        sku_node = card.select_one("form[data-sku]") or card.select_one("[data-sku]")
        sku = (sku_node.get("data-sku") if sku_node else "").strip()

        # Name and Detail link
        name_node = card.select_one(".product-card__name__link") or card.select_one(
            ".product-card__name a"
        )
        if not name_node:
            continue
        name = name_node.get_text(separator=" ", strip=True)
        if not name:
            continue

        rel_href = name_node.get("href") or ""
        source_url = urljoin(BASE_URL, rel_href.strip()) if rel_href else None
        if not source_url or urlparse(source_url).hostname != "www.mytime.de" or not sku:
            continue

        # Current Price only: NOT unit/tier/old
        price_curr_node = card.select_one(".product-card__price--current")
        if not price_curr_node:
            continue
        price_text = price_curr_node.get_text(separator=" ", strip=True)
        try:
            price_cents = extract_price_cents(price_text)
        except (ValueError, ArithmeticError):
            continue

        # Package
        weight_node = card.select_one(".product-card__weight")
        package = weight_node.get_text(strip=True) if weight_node else None

        item = {
            "source": SOURCE_NAME,
            "retailer": RETAILER_NAME,
            "scope": SCOPE,
            "kind": KIND,
            "currency": CURRENCY,
            "ean": None,  # NEVER infer EAN from listing images or SKU
            "name": name,
            "price_cents": price_cents,
            "price_date": observation_date,
            "source_url": source_url,
            "sku": sku or None,
            "source_product_id": sku or None,
            "package_label": package,
            "conditions": CONDITION_TEXT,
            "valid_from": None,
            "valid_until": None,
        }
        products.append(item)

    # Max total pages parsed from pagination links
    total_pages = None
    for a in soup.select("a[href*='page=']"):
        href = a.get("href", "")
        parsed = urlparse(href)
        query = parse_qs(parsed.query)
        if "page" in query:
            for val in query["page"]:
                if val.isdigit():
                    p = int(val)
                    if total_pages is None or p > total_pages:
                        total_pages = p

    return products, total_pages


def _find_products_in_jsonld(data) -> list[dict]:
    found = []
    if isinstance(data, dict):
        typ = data.get("@type")
        if typ == "Product" or (isinstance(typ, list) and "Product" in typ):
            found.append(data)
        for val in data.values():
            found.extend(_find_products_in_jsonld(val))
    elif isinstance(data, list):
        for item in data:
            found.extend(_find_products_in_jsonld(item))
    return found


def parse_detail_page(
    html_content: str, source_url: str, price_date: str | None = None
) -> dict | None:
    """Parses a myTime product detail page JSON-LD metadata.

    Extracts explicit GTIN (gtin/gtin8/gtin13/gtin14) validated by valid_ean.
    Validates currency is EUR.
    Skips AggregateOffer.
    """
    soup = BeautifulSoup(html_content, "html.parser")
    scripts = soup.select("script[type='application/ld+json']")
    candidate_products = []
    for script in scripts:
        content = script.get_text().strip()
        if not content:
            continue
        try:
            parsed = json.loads(content)
            candidate_products.extend(_find_products_in_jsonld(parsed))
        except Exception:
            continue

    if not candidate_products:
        return None

    observation_date = price_date or get_berlin_today()

    for prod in candidate_products:
        raw_name = prod.get("name")
        if not raw_name or not str(raw_name).strip():
            continue
        name = str(raw_name).strip()

        # Explicit GTIN only
        candidate_gtin = None
        for gtin_key in ["gtin14", "gtin13", "gtin8", "gtin", "gtin12"]:
            val = prod.get(gtin_key)
            if val is not None:
                s_val = str(val).strip()
                if valid_ean(s_val):
                    candidate_gtin = s_val
                    break

        # SKU
        sku = str(prod.get("sku") or "").strip() or None

        # Brand
        brand_val = prod.get("brand")
        brand = None
        if isinstance(brand_val, dict):
            brand = str(brand_val.get("name") or "").strip() or None
        elif isinstance(brand_val, str):
            brand = brand_val.strip() or None

        # Offer
        offers = prod.get("offers")
        offer_dict = None
        if isinstance(offers, dict):
            offer_dict = offers
        elif isinstance(offers, list) and offers:
            offer_dict = offers[0]

        if not offer_dict or not isinstance(offer_dict, dict):
            continue

        # Skip AggregateOffer
        offer_type = offer_dict.get("@type")
        if offer_type == "AggregateOffer" or (
            isinstance(offer_type, list) and "AggregateOffer" in offer_type
        ):
            continue

        # Price & Currency: offers.price or offers.priceSpecification.price
        price_val = None
        currency_val = None
        price_spec = offer_dict.get("priceSpecification")
        if isinstance(price_spec, dict):
            price_val = price_spec.get("price")
            currency_val = price_spec.get("priceCurrency")

        if price_val is None:
            price_val = offer_dict.get("price")
        if currency_val is None:
            currency_val = offer_dict.get("priceCurrency")

        if str(currency_val or "").strip().upper() != "EUR":
            # Foreign currency not accepted
            continue

        if price_val is None:
            continue

        try:
            price_cents = cents(price_val)
            if price_cents <= 0:
                continue
        except (ValueError, ArithmeticError):
            continue

        return {
            "source": SOURCE_NAME,
            "retailer": RETAILER_NAME,
            "scope": SCOPE,
            "kind": KIND,
            "currency": CURRENCY,
            "ean": candidate_gtin,
            "name": name,
            "brand": brand,
            "sku": sku,
            "source_product_id": sku,
            "price_cents": price_cents,
            "price_date": observation_date,
            "source_url": source_url,
            "conditions": CONDITION_TEXT,
            "valid_from": None,
            "valid_until": None,
        }

    return None


class AtomicProgressCheckpoint:
    def __init__(self, path: Path = DEFAULT_CHECKPOINT_PATH):
        self.path = Path(path)

    def load(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            with self.path.open("r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning("Could not load checkpoint from %s: %s", self.path, e)
            return {}

    def save(self, data: dict):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(".tmp")
        with tmp_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        tmp_path.replace(self.path)


def clean_unmatched_prior_listing_rows(db: Database, enriched_items: list[dict]):
    """Enrich delete only same source, date, SKU, ean null, and price identical prior listing rows.

    Uses SQLAlchemy to select payload, then executes delete on matched IDs.
    """
    if not enriched_items or not db:
        return 0

    # Group targets by (source, price_date, price_cents, sku)
    targets = set()
    for item in enriched_items:
        sku = item.get("sku")
        price_cents = item.get("price_cents")
        price_date = item.get("price_date")
        source = item.get("source") or SOURCE_NAME
        if item.get("ean") and sku and price_cents is not None and price_date:
            targets.add((source, str(price_date), int(price_cents), str(sku)))

    if not targets:
        return 0

    deleted_count = 0
    with db.engine.connect() as conn:
        query = select(
            observations.c.id,
            observations.c.source,
            observations.c.price_date,
            observations.c.price_cents,
            observations.c.payload_json,
        ).where(
            observations.c.source == SOURCE_NAME,
            observations.c.ean.is_(None),
        )
        rows = conn.execute(query).fetchall()

        matched_ids = []
        for row in rows:
            row_id, r_source, r_date, r_cents, payload_raw = row
            try:
                payload = json.loads(payload_raw) if isinstance(payload_raw, str) else payload_raw
            except Exception:
                continue
            r_sku = str(payload.get("sku") or "").strip()
            if (r_source, str(r_date), int(r_cents), r_sku) in targets:
                matched_ids.append(row_id)

    if matched_ids:
        with db.engine.begin() as write_conn:
            for i in range(0, len(matched_ids), 200):
                chunk = matched_ids[i : i + 200]
                write_conn.execute(delete(observations).where(observations.c.id.in_(chunk)))
            deleted_count = len(matched_ids)

    return deleted_count


class MyTimeExpandedFeedSync:
    def __init__(
        self,
        db: Database,
        checkpoint_path: Path = DEFAULT_CHECKPOINT_PATH,
        lock_path: Path | None = None,
        delay: float = 0.5,
        workers: int = 3,
        interval_hours: float = DEFAULT_INTERVAL_HOURS,
    ):
        self.db = db
        self.obs_repo = ObservationRepository(db) if db else None
        self.product_repo = ProductRepository(db) if db else None
        self.checkpoint_path = Path(checkpoint_path)
        self.checkpoint_mgr = AtomicProgressCheckpoint(self.checkpoint_path)
        self.lock_path = Path(lock_path) if lock_path else self.checkpoint_path.with_suffix(".lock")
        self.delay = delay
        self.workers = max(1, workers)
        self.interval_hours = interval_hours

    def _get_headers(self) -> dict:
        return {
            "User-Agent": "PriceWatch/1.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
        }

    @contextmanager
    def _acquire_lock(self):
        if fcntl is None:
            yield None
            return
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.lock_path.open("a+")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (BlockingIOError, OSError) as exc:
            handle.close()
            raise LockError(f"Sync lock held by another process: {self.lock_path}") from exc
        try:
            yield handle
        finally:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
            handle.close()

    def seed_verified_gtins_from_db(self) -> dict[str, str]:
        """Loads known explicit SKU->EAN mappings from existing database observations."""
        if not self.db:
            return {}
        mapping = {}
        try:
            with self.db.engine.connect() as conn:
                query = select(
                    observations.c.ean,
                    observations.c.payload_json,
                ).where(
                    observations.c.source == SOURCE_NAME,
                    observations.c.ean.isnot(None),
                )
                rows = conn.execute(query).fetchall()
                for ean, payload_raw in rows:
                    if not ean or not valid_ean(str(ean)):
                        continue
                    try:
                        payload = (
                            json.loads(payload_raw) if isinstance(payload_raw, str) else payload_raw
                        )
                        sku = str(payload.get("sku") or "").strip()
                        if sku:
                            mapping[sku] = str(ean)
                    except Exception:
                        continue
        except Exception as e:
            logger.warning("Could not seed verified gtins from DB: %s", e)
        return mapping

    def sync_listing(
        self,
        max_pages: int = 300,
        reset: bool = False,
        interval_hours: float | None = None,
    ) -> dict:
        try:
            with self._acquire_lock():
                return self._sync_listing_locked(
                    max_pages=max_pages,
                    reset=reset,
                    interval_hours=interval_hours,
                )
        except LockError as exc:
            logger.warning("Listing sync locked: %s", exc)
            return {"status": "locked", "message": str(exc)}

    def _sync_listing_locked(
        self,
        max_pages: int,
        reset: bool,
        interval_hours: float | None,
    ) -> dict:
        data = self.checkpoint_mgr.load() if not reset else {}
        eff_interval = self.interval_hours if interval_hours is None else interval_hours

        # Handle hard reset request
        if reset:
            old_checkpoint = self.checkpoint_mgr.load()
            existing_verified = old_checkpoint.get("verified_gtins", {})
            if not existing_verified:
                existing_verified = self.seed_verified_gtins_from_db()
            data = {
                "cycle_started_at": time.time(),
                "listing_status": "in_progress",
                "listing_completed_at": None,
                "next_page": 1,
                "total_pages": None,
                "product_url_map": {},
                "enriched_skus": [],
                "cooldown_until": old_checkpoint.get("cooldown_until"),
                "verified_gtins": existing_verified,
            }
            self.checkpoint_mgr.save(data)
        elif not data:
            data = {
                "cycle_started_at": time.time(),
                "listing_status": "in_progress",
                "listing_completed_at": None,
                "next_page": 1,
                "total_pages": None,
                "product_url_map": {},
                "enriched_skus": [],
                "cooldown_until": None,
                "verified_gtins": self.seed_verified_gtins_from_db(),
            }
            self.checkpoint_mgr.save(data)

        # Preserve known verified gtins if missing from loaded data
        verified_gtins = data.setdefault("verified_gtins", {})
        if not verified_gtins:
            verified_gtins.update(self.seed_verified_gtins_from_db())
            data["verified_gtins"] = verified_gtins
            self.checkpoint_mgr.save(data)

        # Respect active rate limit cooldown across midnight and restarts
        cooldown_until = data.get("cooldown_until")
        if cooldown_until and time.time() < cooldown_until:
            logger.warning("In cooldown until %s. Halting listing crawl.", cooldown_until)
            return {"status": "cooldown", "cooldown_until": cooldown_until}

        # Check if completed listing cycle is due for restart
        listing_status = data.get("listing_status")
        listing_completed_at = data.get("listing_completed_at")
        is_already_completed = listing_status == "completed" or (
            data.get("total_pages") is not None and data.get("next_page", 1) > data["total_pages"]
        )

        if is_already_completed:
            if listing_completed_at:
                elapsed = time.time() - listing_completed_at
                interval_seconds = eff_interval * 3600.0
                if elapsed < interval_seconds:
                    next_due = max(0, int(interval_seconds - elapsed))
                    logger.info(
                        "Listing cycle completed %.1fh ago, next restart due in %.1fh",
                        elapsed / 3600.0,
                        next_due / 3600.0,
                    )
                    return {
                        "status": "idle",
                        "message": "Listing cycle already completed and not due yet",
                        "listing_completed_at": listing_completed_at,
                        "next_due_in_seconds": next_due,
                        "total_products_mapped": len(data.get("product_url_map", {})),
                    }

            # Restart when due: fresh cycle, preserving verified SKU->EAN mappings
            logger.info(
                "Listing cycle restart due (%.1fh interval). Starting fresh cycle.", eff_interval
            )
            data["cycle_started_at"] = time.time()
            data["listing_status"] = "in_progress"
            data["listing_completed_at"] = None
            data["next_page"] = 1
            data["total_pages"] = None
            data["product_url_map"] = {}
            data["enriched_skus"] = []
            self.checkpoint_mgr.save(data)

        next_page = data.get("next_page", 1)
        total_pages = data.get("total_pages")
        product_url_map = data.get("product_url_map", {})
        total_saved = 0
        pages_processed = 0

        client = httpx.Client(headers=self._get_headers(), timeout=30.0, follow_redirects=True)
        try:
            while pages_processed < max_pages:
                if total_pages is not None and next_page > total_pages:
                    logger.info("Reached last page (%d > %d)", next_page, total_pages)
                    break

                url = LISTING_URL_TEMPLATE.format(page=next_page)
                logger.info("Fetching listing page %d: %s", next_page, url)
                try:
                    resp = client.get(url)
                except Exception as e:
                    logger.error("HTTP request error fetching page %d: %s", next_page, e)
                    # Failure does not advance page or mark prices fresh
                    break

                if resp.status_code in (403, 429):
                    logger.warning(
                        "Rate limit or blocked: status %d on page %d", resp.status_code, next_page
                    )
                    cd = time.time() + retry_delay(resp.headers.get("Retry-After"))
                    data["cooldown_until"] = cd
                    self.checkpoint_mgr.save(data)
                    return {
                        "status": "cooldown",
                        "cooldown_until": cd,
                        "pages_processed": pages_processed,
                        "total_saved": total_saved,
                        "next_page": next_page,
                        "total_pages": total_pages,
                        "total_products_mapped": len(product_url_map),
                    }

                if resp.status_code >= 400:
                    logger.error("HTTP %d error on page %d", resp.status_code, next_page)
                    # Failure does not advance page or mark prices fresh
                    break

                today_date = get_berlin_today()
                prods, detected_total = parse_listing_page(resp.text, price_date=today_date)

                # Attach explicit SKU->EAN mappings to fresh listing prices.
                for product in prods:
                    sku = product.get("sku")
                    if sku and sku in verified_gtins:
                        product["ean"] = verified_gtins[sku]

                if detected_total and (total_pages is None or detected_total > total_pages):
                    total_pages = detected_total
                    data["total_pages"] = total_pages

                # Save observations in DB
                if prods:
                    if self.obs_repo:
                        self.obs_repo.save(prods)
                    total_saved += len(prods)
                    for p in prods:
                        sku = p.get("sku")
                        if p.get("source_url") and sku:
                            product_url_map[sku] = {
                                "url": p["source_url"],
                                "name": p["name"],
                                "price_cents": p["price_cents"],
                                "price_date": p["price_date"],
                                "package_label": p.get("package_label"),
                            }

                pages_processed += 1
                next_page += 1
                data["next_page"] = next_page
                data["product_url_map"] = product_url_map
                self.checkpoint_mgr.save(data)

                if pages_processed < max_pages and self.delay > 0:
                    time.sleep(self.delay)
        finally:
            client.close()

        is_completed = total_pages is not None and next_page > total_pages
        if is_completed:
            data["listing_status"] = "completed"
            data["listing_completed_at"] = time.time()
            self.checkpoint_mgr.save(data)

        return {
            "status": "completed" if is_completed else "in_progress",
            "pages_processed": pages_processed,
            "total_saved": total_saved,
            "next_page": next_page,
            "total_pages": total_pages,
            "total_products_mapped": len(product_url_map),
        }

    def sync_enrich(
        self,
        max_details: int = 1000,
        reset: bool = False,
    ) -> dict:
        try:
            with self._acquire_lock():
                return self._sync_enrich_locked(
                    max_details=max_details,
                    reset=reset,
                )
        except LockError as exc:
            logger.warning("Enrich sync locked: %s", exc)
            return {"status": "locked", "message": str(exc)}

    def _sync_enrich_locked(
        self,
        max_details: int,
        reset: bool,
    ) -> dict:
        data = self.checkpoint_mgr.load()
        if not data:
            logger.warning("Checkpoint empty. Cannot enrich without listing.")
            return {"status": "no_checkpoint_data"}

        cooldown_until = data.get("cooldown_until")
        if cooldown_until and time.time() < cooldown_until:
            logger.warning("In cooldown until %s. Halting enrich crawl.", cooldown_until)
            return {"status": "cooldown", "cooldown_until": cooldown_until}

        if not data.get("product_url_map"):
            logger.warning("Missing product map in checkpoint. Cannot enrich without listing.")
            return {"status": "no_checkpoint_data"}

        enriched_skus = set(data.get("enriched_skus", []))
        if reset:
            enriched_skus = set()
            data["enriched_skus"] = []
            self.checkpoint_mgr.save(data)

        verified = data.setdefault("verified_gtins", {})
        if not verified:
            verified.update(self.seed_verified_gtins_from_db())
            data["verified_gtins"] = verified
            self.checkpoint_mgr.save(data)

        product_map = data.get("product_url_map", {})

        # Skip known EANs and details already checked during this cycle.
        pending_skus = [
            sku for sku in product_map if sku not in enriched_skus and sku not in verified
        ]

        if not pending_skus:
            return {
                "status": "already_completed",
                "processed": 0,
                "enriched_total": len(enriched_skus),
                "explicit_gtins": len(verified),
            }

        pending_skus = pending_skus[:max_details]
        logger.info("Enriching up to %d detail URLs...", len(pending_skus))

        processed_count = 0
        with httpx.Client(headers=self._get_headers(), timeout=30, follow_redirects=True) as client:

            def fetch(sku):
                if self.delay > 0:
                    time.sleep(self.delay)
                url = product_map[sku]["url"]
                try:
                    response = client.get(url)
                    if response.status_code in (403, 429):
                        return sku, None, retry_delay(response.headers.get("Retry-After"))
                    response.raise_for_status()
                    item = parse_detail_page(response.text, url, get_berlin_today())
                    if item and item.get("sku") != sku:
                        item = None
                    return sku, item, 0
                except httpx.HTTPError as error:
                    logger.warning("Detail request failed %s: %s", sku, type(error).__name__)
                    return sku, None, -1
                except Exception as error:
                    logger.warning("Unexpected error fetching detail %s: %s", sku, error)
                    return sku, None, -1

            with ThreadPoolExecutor(max_workers=min(self.workers, 4)) as pool:
                for start in range(0, len(pending_skus), 30):
                    batch = []
                    catalog = []
                    stopped_by_cooldown = False
                    for sku, item, failure in pool.map(fetch, pending_skus[start : start + 30]):
                        if failure != 0:
                            if failure > 0:
                                data["cooldown_until"] = time.time() + failure
                                stopped_by_cooldown = True
                            # Failure (whether cooldown or network/HTTP):
                            # Do NOT add to enriched_skus (not permanently skipped).
                            # Do NOT mark prices fresh.
                            continue

                        # Successfully fetched (HTTP 200)
                        enriched_skus.add(sku)
                        processed_count += 1
                        if item and item.get("ean"):
                            listing_info = product_map[sku]
                            # The detail response supplies its own current price and date.
                            # Never assign today's date to an older cached listing price.
                            item["package_label"] = listing_info.get("package_label")
                            batch.append(item)
                            verified[sku] = item["ean"]
                            catalog.append(
                                ProductInput(
                                    ean=item["ean"],
                                    name=item["name"][:300],
                                    brand=item.get("brand"),
                                    package_label=item.get("package_label"),
                                    countries=["en:germany"],
                                    reported_stores=RETAILER_NAME,
                                    source_url=item["source_url"],
                                )
                            )

                    self._flush_batch(batch, catalog)
                    data["enriched_skus"] = sorted(enriched_skus)
                    data["verified_gtins"] = verified
                    self.checkpoint_mgr.save(data)
                    logger.info(
                        "Detail checkpoint: %d checked, %d explicit GTINs",
                        len(enriched_skus),
                        len(verified),
                    )
                    if stopped_by_cooldown:
                        return {
                            "status": "cooldown",
                            "cooldown_until": data["cooldown_until"],
                            "processed": processed_count,
                            "enriched_total": len(enriched_skus),
                            "explicit_gtins": len(verified),
                        }

        remaining = [sku for sku in product_map if sku not in enriched_skus and sku not in verified]
        return {
            "status": "completed" if len(remaining) == 0 else "in_progress",
            "processed": processed_count,
            "enriched_total": len(enriched_skus),
            "explicit_gtins": len(verified),
        }

    def _flush_batch(self, observations_batch: list[dict], catalog_batch: list[ProductInput]):
        if catalog_batch and self.product_repo:
            self.product_repo.upsert(catalog_batch, source="retailer_observation")
        if observations_batch and self.obs_repo:
            self.obs_repo.save(observations_batch)
            # Clean up prior listing rows matching source, date, sku, ean null, and identical price
            deleted = clean_unmatched_prior_listing_rows(self.db, observations_batch)
            logger.info(
                "Saved %d enriched observations and purged %d prior listing rows",
                len(observations_batch),
                deleted,
            )
