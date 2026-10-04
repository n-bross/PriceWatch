"""Tests for myTime expanded feeds listing, detail parser, tier pricing, and checkpoint handling."""

import fcntl
import json
from unittest.mock import MagicMock, patch

import httpx
import pytest

from pricewatch_api.database import Database
from pricewatch_api.expanded_feeds import (
    AtomicProgressCheckpoint,
    MyTimeExpandedFeedSync,
    clean_unmatched_prior_listing_rows,
    extract_price_cents,
    parse_detail_page,
    parse_listing_page,
)
from pricewatch_api.observations import ObservationRepository

SAMPLE_CARD_HTML = """<div id="product-list-210000000"><li class="product-card">
<a class="product-card__name__link" href="/jeden_tag_fettarme_h-milch_1-5_prozent_4503080043.html">
Jeden Tag fettarme H-Milch 1,5%</a>
<img src="https://example.com/4306188362562.jpg">
<small class="product-card__weight">1 l</small>
<div class="product-card__price--current">1,19 €</div>
<div class="product-card__bulk-price">1,19 €/1 l</div>
<form data-sku="4503080043"></form>
<details>ab 3 Stück 5% sparen</details></li></div>"""

PAGINATION_HTML = '<a href="?page=257">257</a>'

SAMPLE_DETAIL_JSONLD = """
{
    "@context": "https://schema.org",
    "@type": "Product",
    "name": "Red Bull Energy Drink The Glacier Edition Gletschereis-Himbeere (Einweg)",
    "description": "RED BULL VERLEIHT FLUEGEL",
    "sku": "4504052446",
    "gtin": "90486647",
    "manufacturer": {
        "@type": "Organization",
        "name": "Red Bull"
    },
    "brand": {
        "@type": "Brand",
        "name": "Red Bull"
    },
    "image": "https://d2y99t05v0nd2u.cloudfront.net/products/images/4504052446_90486647_01.jpg",
    "offers": {
        "@type": "Offer",
        "availability": "https://schema.org/InStock",
        "itemCondition": "https://schema.org/NewCondition",
        "priceSpecification": {
            "@type": "UnitPriceSpecification",
            "price": "1.89",
            "priceCurrency": "EUR",
            "valueAddedTaxIncluded": true
        }
    }
}
"""


def test_extract_price_cents():
    assert extract_price_cents("1,19 €") == 119
    assert extract_price_cents("0,99 € / 100g") == 99
    assert extract_price_cents("12.50 EUR") == 1250
    with pytest.raises(ValueError):
        extract_price_cents("Free")


def test_parse_listing_page_extracts_correct_fields():
    html = f"<div id='product-list-210000000'>{SAMPLE_CARD_HTML}</div>{PAGINATION_HTML}"
    prods, total_pages = parse_listing_page(html, price_date="2025-05-10")
    assert total_pages == 257
    assert len(prods) == 1
    p = prods[0]
    assert p["name"] == "Jeden Tag fettarme H-Milch 1,5%"
    assert p["price_cents"] == 119
    assert p["ean"] is None  # Never inferred from image CloudFront URL
    assert p["sku"] == "4503080043"
    assert p["package_label"] == "1 l"
    assert (
        p["source_url"]
        == "https://www.mytime.de/jeden_tag_fettarme_h-milch_1-5_prozent_4503080043.html"
    )
    assert p["price_date"] == "2025-05-10"
    assert p["currency"] == "EUR"
    assert p["conditions"] == "Onlinepreis zzgl. Versand; Mengenrabatte nicht eingerechnet"


def test_parse_listing_page_ignores_tier_and_bulk_prices():
    # Modify current price and ensure tier/bulk prices are not chosen
    card_with_tier = SAMPLE_CARD_HTML.replace("1,19 €", "2,49 €").replace(
        "1,19 €/1 l", "0,99 €/1 l"
    )
    prods, _ = parse_listing_page(card_with_tier)
    assert len(prods) == 1
    assert prods[0]["price_cents"] == 249  # current price, not bulk or tier


def test_parse_detail_page_valid_gtin():
    html = f"<script type='application/ld+json'>{SAMPLE_DETAIL_JSONLD}</script>"
    url = "https://www.mytime.de/red_bull_4504052446.html"
    detail = parse_detail_page(html, source_url=url, price_date="2025-05-10")
    assert detail is not None
    assert detail["ean"] == "90486647"  # valid 8-digit EAN
    assert detail["price_cents"] == 189
    assert detail["currency"] == "EUR"
    assert detail["sku"] == "4504052446"
    assert detail["brand"] == "Red Bull"
    assert detail["source_url"] == url


def test_parse_detail_page_invalid_gtin_rejected():
    bad_jsonld = json.loads(SAMPLE_DETAIL_JSONLD)
    bad_jsonld["gtin"] = "1234567"  # invalid length & checksum
    html = f"<script type='application/ld+json'>{json.dumps(bad_jsonld)}</script>"
    detail = parse_detail_page(html, source_url="https://www.mytime.de/test.html")
    assert detail is not None
    assert detail["ean"] is None  # invalid GTIN rejected


def test_parse_detail_page_foreign_currency_rejected():
    foreign_jsonld = json.loads(SAMPLE_DETAIL_JSONLD)
    foreign_jsonld["offers"]["priceSpecification"]["priceCurrency"] = "USD"
    html = f"<script type='application/ld+json'>{json.dumps(foreign_jsonld)}</script>"
    detail = parse_detail_page(html, source_url="https://www.mytime.de/test.html")
    assert detail is None


def test_parse_detail_page_aggregate_offer_skipped():
    agg_jsonld = json.loads(SAMPLE_DETAIL_JSONLD)
    agg_jsonld["offers"]["@type"] = "AggregateOffer"
    html = f"<script type='application/ld+json'>{json.dumps(agg_jsonld)}</script>"
    detail = parse_detail_page(html, source_url="https://www.mytime.de/test.html")
    assert detail is None


def test_checkpoint_atomic_save_and_load(tmp_path):
    ckpt_file = tmp_path / "checkpoint.json"
    mgr = AtomicProgressCheckpoint(ckpt_file)
    data = {"checkpoint_date": "2025-05-10", "next_page": 5, "total_pages": 257}
    mgr.save(data)
    loaded = mgr.load()
    assert loaded == data


def test_clean_unmatched_prior_listing_rows(tmp_path):
    db = Database("sqlite:///:memory:")
    db.initialize()
    repo = ObservationRepository(db)

    # Insert initial listing row with ean=None
    listing_entry = {
        "source": "mytime_website",
        "retailer": "myTime",
        "scope": "online",
        "kind": "unknown",
        "currency": "EUR",
        "ean": None,
        "name": "Test Item",
        "price_cents": 199,
        "price_date": "2025-05-10",
        "source_url": "https://www.mytime.de/test_item.html",
        "sku": "SKU123",
        "condition": "Onlinepreis zzgl. Versand; Mengenrabatte nicht eingerechnet",
    }
    repo.save([listing_entry])

    status = repo.query(source="mytime_website")
    assert status["total"] == 1

    # Enriched item with valid EAN-8 90486647
    enriched_item = {
        "source": "mytime_website",
        "retailer": "myTime",
        "scope": "online",
        "kind": "unknown",
        "currency": "EUR",
        "ean": "90486647",
        "name": "Test Item",
        "price_cents": 199,
        "price_date": "2025-05-10",
        "sku": "SKU123",
        "source_url": "https://www.mytime.de/test_item.html",
    }
    repo.save([enriched_item])

    # Now 2 entries exist in observations
    assert repo.query(source="mytime_website")["total"] == 2

    # Run clean_unmatched_prior_listing_rows
    deleted = clean_unmatched_prior_listing_rows(db, [enriched_item])
    assert deleted == 1

    # Only the enriched row (with explicit EAN) remains
    remaining = repo.query(source="mytime_website")
    assert remaining["total"] == 1
    assert remaining["items"][0]["ean"] == "90486647"


# --- NEW COMPREHENSIVE TESTS FOR EFFICIENT REPEATABLE MYTIME SYNC ---


def test_bounded_listing_resumes_across_midnight(tmp_path):
    """Bounded import resumes where it left off across midnight without discarding progress."""
    db = Database("sqlite:///:memory:")
    db.initialize()
    ckpt_file = tmp_path / "progress.json"

    # Pre-populate checkpoint as if page 1 was scraped yesterday
    mgr = AtomicProgressCheckpoint(ckpt_file)
    mgr.save(
        {
            "cycle_started_at": 1000.0,
            "listing_status": "in_progress",
            "listing_completed_at": None,
            "next_page": 2,
            "total_pages": 5,
            "product_url_map": {
                "SKU_PAGE1": {
                    "url": "https://www.mytime.de/p1.html",
                    "name": "Product 1",
                    "price_cents": 100,
                    "price_date": "2026-10-03",
                }
            },
            "verified_gtins": {},
        }
    )

    sync = MyTimeExpandedFeedSync(db=db, checkpoint_path=ckpt_file, delay=0)

    page2_html = SAMPLE_CARD_HTML.replace("4503080043", "SKU_PAGE2") + '<a href="?page=5">5</a>'
    mock_resp = MagicMock(status_code=200, text=page2_html)

    with patch("httpx.Client.get", return_value=mock_resp):
        res = sync.sync_listing(max_pages=1)

    assert res["status"] == "in_progress"
    assert res["pages_processed"] == 1
    assert res["next_page"] == 3

    # Checkpoint must preserve SKU_PAGE1 and contain SKU_PAGE2
    saved_data = mgr.load()
    assert saved_data["next_page"] == 3
    assert "SKU_PAGE1" in saved_data["product_url_map"]
    assert "SKU_PAGE2" in saved_data["product_url_map"]


def test_completed_listing_cycles_restart_when_due(tmp_path):
    """Completed listings stay idle until due, then restart."""
    db = Database("sqlite:///:memory:")
    db.initialize()
    ckpt_file = tmp_path / "progress.json"
    mgr = AtomicProgressCheckpoint(ckpt_file)

    now = 100_000.0
    mgr.save(
        {
            "cycle_started_at": now - 3600.0,
            "listing_status": "completed",
            "listing_completed_at": now - 3600.0,  # 1 hour ago
            "next_page": 6,
            "total_pages": 5,
            "product_url_map": {
                "SKU_OLD": {"url": "https://www.mytime.de/old.html", "price_cents": 200}
            },
            "verified_gtins": {"SKU_OLD": "90486647"},
        }
    )

    sync = MyTimeExpandedFeedSync(db=db, checkpoint_path=ckpt_file, delay=0, interval_hours=24.0)

    # 1. Called before due (1 hour elapsed < 24h default): must be idle, no HTTP calls
    with patch("time.time", return_value=now):
        with patch("httpx.Client.get") as mock_get:
            res = sync.sync_listing(max_pages=1, interval_hours=24.0)
            assert res["status"] == "idle"
            assert "already completed" in res["message"].lower()
            mock_get.assert_not_called()

    # Restart after 25h, preserving verified GTINs.
    due_time = now + 86400.0 + 3600.0
    page1_html = SAMPLE_CARD_HTML.replace("4503080043", "SKU_CYCLE2") + '<a href="?page=5">5</a>'
    mock_resp = MagicMock(status_code=200, text=page1_html)

    with patch("time.time", return_value=due_time):
        with patch("httpx.Client.get", return_value=mock_resp):
            res = sync.sync_listing(max_pages=1, interval_hours=24.0)
            assert res["status"] == "in_progress"
            assert res["pages_processed"] == 1
            assert res["next_page"] == 2

    # Verified GTINs must be preserved across cycles
    saved = mgr.load()
    assert saved["verified_gtins"].get("SKU_OLD") == "90486647"
    assert "SKU_CYCLE2" in saved["product_url_map"]


def test_sync_lock_prevents_overlapping_processes(tmp_path):
    """File lock prevents concurrent listing or enrich executions."""
    db = Database("sqlite:///:memory:")
    db.initialize()
    ckpt_file = tmp_path / "progress.json"
    lock_file = tmp_path / "progress.lock"

    sync = MyTimeExpandedFeedSync(
        db=db,
        checkpoint_path=ckpt_file,
        lock_path=lock_file,
        delay=0,
    )

    # Acquire lock externally simulating another process
    with lock_file.open("w") as external_handle:
        fcntl.flock(external_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

        # sync_listing must fail gracefully with status "locked"
        res_listing = sync.sync_listing()
        assert res_listing["status"] == "locked"
        assert "held by another process" in res_listing["message"]

        # sync_enrich must also fail gracefully with status "locked"
        res_enrich = sync.sync_enrich()
        assert res_enrich["status"] == "locked"
        assert "held by another process" in res_enrich["message"]

        # Release lock
        fcntl.flock(external_handle.fileno(), fcntl.LOCK_UN)

    # Once lock is free, sync_listing proceeds
    with patch("httpx.Client.get", return_value=MagicMock(status_code=200, text=SAMPLE_CARD_HTML)):
        res = sync.sync_listing(max_pages=1)
        assert res["status"] in ("in_progress", "completed")


def test_http_429_triggers_cooldown_and_halts(tmp_path):
    """HTTP 429 stops processing and prevents calls during cooldown."""
    db = Database("sqlite:///:memory:")
    db.initialize()
    ckpt_file = tmp_path / "progress.json"
    sync = MyTimeExpandedFeedSync(db=db, checkpoint_path=ckpt_file, delay=0)

    # Mock response returning 429 with Retry-After 600
    mock_resp = MagicMock(status_code=429, headers={"Retry-After": "600"})

    now = 50_000.0
    with patch("time.time", return_value=now):
        with patch("httpx.Client.get", return_value=mock_resp):
            res = sync.sync_listing(max_pages=2)
            assert res["status"] == "cooldown"
            assert res["cooldown_until"] >= now + 300

    # Next call while still in cooldown returns immediately without making HTTP calls
    with patch("time.time", return_value=now + 100):
        with patch("httpx.Client.get") as mock_get:
            res_repeat = sync.sync_listing(max_pages=1)
            assert res_repeat["status"] == "cooldown"
            mock_get.assert_not_called()

            # Enrich also honors the cooldown
            res_enrich = sync.sync_enrich()
            assert res_enrich["status"] == "cooldown"
            mock_get.assert_not_called()


def test_sync_enrich_failure_does_not_mark_fresh_or_permanently_skip(tmp_path):
    """Enrich failure does not save fresh prices or permanently skip detail items."""
    db = Database("sqlite:///:memory:")
    db.initialize()
    ckpt_file = tmp_path / "progress.json"
    mgr = AtomicProgressCheckpoint(ckpt_file)

    mgr.save(
        {
            "product_url_map": {
                "SKU_FAIL": {
                    "url": "https://www.mytime.de/fail.html",
                    "name": "Failing Item",
                    "price_cents": 299,
                    "price_date": "2026-10-04",
                },
                "SKU_SUCCESS": {
                    "url": "https://www.mytime.de/success.html",
                    "name": "Success Item",
                    "price_cents": 189,
                    "price_date": "2026-10-04",
                },
            },
            "enriched_skus": [],
            "verified_gtins": {},
        }
    )

    sync = MyTimeExpandedFeedSync(db=db, checkpoint_path=ckpt_file, delay=0)

    def mock_get(url, **kwargs):
        if "fail.html" in str(url):
            raise httpx.ConnectError("Connection timed out")
        resp = MagicMock(status_code=200)
        resp.text = (
            "<script type='application/ld+json'>"
            + SAMPLE_DETAIL_JSONLD.replace("4504052446", "SKU_SUCCESS")
            + "</script>"
        )
        return resp

    with patch("httpx.Client.get", side_effect=mock_get):
        res = sync.sync_enrich(max_details=10)

    assert res["processed"] == 1
    saved = mgr.load()

    # Success SKU is marked enriched and verified
    assert "SKU_SUCCESS" in saved["enriched_skus"]
    assert saved["verified_gtins"].get("SKU_SUCCESS") == "90486647"

    # Failed SKU MUST NOT be marked enriched (never permanently skipped)
    assert "SKU_FAIL" not in saved["enriched_skus"]

    # Verify DB: Only SKU_SUCCESS was saved as enriched observation
    repo = ObservationRepository(db)
    obs = repo.query(source="mytime_website")
    assert obs["total"] == 1
    assert obs["items"][0]["ean"] == "90486647"

    # Calling enrich again retries the failed SKU
    def mock_retry_get(url, **kwargs):
        resp = MagicMock(status_code=200)
        resp.text = (
            "<script type='application/ld+json'>"
            + SAMPLE_DETAIL_JSONLD.replace("4504052446", "SKU_FAIL")
            + "</script>"
        )
        return resp

    with patch("httpx.Client.get", side_effect=mock_retry_get):
        res_retry = sync.sync_enrich(max_details=10)
        assert res_retry["processed"] == 1

    saved_after_retry = mgr.load()
    assert "SKU_FAIL" in saved_after_retry["enriched_skus"]


def test_persist_verified_gtins_reduces_detail_calls_and_preserves_listing_price(tmp_path):
    """Known EANs reduce detail calls and keep the listing price."""
    db = Database("sqlite:///:memory:")
    db.initialize()
    ckpt_file = tmp_path / "progress.json"
    mgr = AtomicProgressCheckpoint(ckpt_file)

    # Pre-populate known SKU->EAN mapping
    mgr.save(
        {
            "verified_gtins": {"4503080043": "90486647"},
            "product_url_map": {},
            "next_page": 1,
            "total_pages": None,
        }
    )

    sync = MyTimeExpandedFeedSync(db=db, checkpoint_path=ckpt_file, delay=0)

    # Scrape listing page containing 4503080043 (current price 1.19 EUR = 119 cents)
    with patch("httpx.Client.get", return_value=MagicMock(status_code=200, text=SAMPLE_CARD_HTML)):
        sync.sync_listing(max_pages=1)

    # Listing observation should IMMEDIATELY have the explicit EAN and exact listing price
    repo = ObservationRepository(db)
    obs = repo.query(source="mytime_website")
    assert obs["total"] == 1
    assert obs["items"][0]["ean"] == "90486647"
    assert obs["items"][0]["price_cents"] == 119  # exact listing price retained

    # When sync_enrich runs, it recognizes 4503080043 is already verified -> ZERO detail HTTP calls!
    with patch("httpx.Client.get") as detail_get:
        res = sync.sync_enrich(max_details=10)
        assert res["status"] in ("already_completed", "completed")
        assert res["processed"] == 0
        detail_get.assert_not_called()


def test_seed_verified_gtins_from_db(tmp_path):
    """Verified GTINs are seeded from existing database observations across fresh checkpoints."""
    db = Database("sqlite:///:memory:")
    db.initialize()
    repo = ObservationRepository(db)

    # Existing observation in DB from previous run with explicit EAN
    repo.save(
        [
            {
                "source": "mytime_website",
                "retailer": "myTime",
                "scope": "online",
                "kind": "unknown",
                "currency": "EUR",
                "ean": "90486647",
                "name": "Milch",
                "price_cents": 119,
                "sku": "SKU_DB_123",
                "source_url": "https://www.mytime.de/milch.html",
            }
        ]
    )

    ckpt_file = tmp_path / "fresh_checkpoint.json"
    sync = MyTimeExpandedFeedSync(db=db, checkpoint_path=ckpt_file, delay=0)

    seeded = sync.seed_verified_gtins_from_db()
    assert seeded.get("SKU_DB_123") == "90486647"


def test_later_detail_fetch_does_not_freshen_legacy_listing_price(tmp_path):
    db = Database("sqlite:///:memory:")
    db.initialize()
    path = tmp_path / "progress.json"
    AtomicProgressCheckpoint(path).save(
        {
            "checkpoint_date": "2026-10-01",
            "product_url_map": {
                "4504052446": {
                    "url": "https://www.mytime.de/item.html",
                    "price_cents": 99,
                }
            },
        }
    )
    sync = MyTimeExpandedFeedSync(db, checkpoint_path=path, delay=0)
    html = '<script type="application/ld+json">' + SAMPLE_DETAIL_JSONLD + "</script>"
    with patch("httpx.Client.get", return_value=MagicMock(status_code=200, text=html)):
        with patch("pricewatch_api.expanded_feeds.get_berlin_today", return_value="2026-10-04"):
            sync.sync_enrich(max_details=1)
    items = ObservationRepository(db).query(source="mytime_website")["items"]
    assert len(items) == 1
    assert items[0]["price_date"] == "2026-10-04"
    assert items[0]["price_cents"] == 189  # New detail price, not cached 99 cents.
