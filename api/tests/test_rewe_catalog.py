import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from pricewatch_api.database import Database
from pricewatch_api.observations import ObservationRepository
from pricewatch_api.rewe_catalog import category_slugs, sync_catalog
from pricewatch_api.rewe_recurring import SOURCE

NOW = datetime(2026, 10, 4, 18, tzinfo=UTC)


@pytest.fixture
def payload():
    p = json.loads((Path(__file__).parent / "fixtures/rewe-shop.json").read_text())
    p["facets"] = [
        {
            "name": "CATEGORY",
            "facetConstraints": [
                {"slug": "seasonal", "categoryTags": ["inspiration"]},
                {"slug": "food"},
                {"slug": "drinks"},
            ],
        }
    ]
    return p


@pytest.fixture
def db(tmp_path):
    database = Database(f"sqlite:///{tmp_path / 'prices.db'}")
    database.initialize()
    yield database
    database.engine.dispose()


def test_discovery_requires_market_and_excludes_editorial_collections(payload):
    assert category_slugs(payload, "461766") == ["food", "drinks"]
    with pytest.raises(ValueError):
        category_slugs(payload, "other")


def test_resume_visits_all_categories_and_deduplicates_articles(tmp_path, db, payload):
    requests = []

    def respond(request):
        requests.append(dict(request.url.params))
        p = deepcopy(payload)
        category = request.url.params.get("categorySlug")
        if category:
            assert "attribute" not in request.url.params  # Includes non-discounted articles.
            page = int(request.url.params["page"])
            p["pagination"].update(
                page=page,
                totalPages=2 if category == "food" else 1,
                totalResultCount=8 if category == "food" else 4,
            )
            if page == 2:
                for item in p["_embedded"]["products"]:
                    item["id"] += "-second"
                    item["_embedded"]["articles"][0]["_embedded"]["listing"]["pricing"].pop(
                        "discount", None
                    )
        return httpx.Response(200, json=p)

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        result = sync_catalog(tmp_path, db, client, "461766", "85567", 1, 0, NOW)
        assert result["status"] == "in_progress"
        assert result["cycle_articles"] == 4
        result = sync_catalog(tmp_path, db, client, "461766", "85567", 1, 0, NOW)
        assert result["cycle_articles"] == 4
        result = sync_catalog(tmp_path, db, client, "461766", "85567", 1, 0, NOW)
        assert result["status"] == "completed"
        assert result["cycle_articles"] == 8
        assert result["pages_completed"] == 3
        assert result["categories_completed"] == 2
        assert (
            sync_catalog(tmp_path, db, client, "461766", "85567", now=NOW)["status"] == "cooldown"
        )
    assert len(requests) == 4  # One discovery request, then three pages across resumed batches.
    items = ObservationRepository(db).query(source=SOURCE)["items"]
    assert len(items) == 8
    assert all(p["channel"] == "pickup" and p["store_id"] == "461766" for p in items)
    assert sum(p["valid_until"] is None for p in items) == 4


def test_failed_page_retains_checkpoint_and_successful_prices(tmp_path, db, payload):
    payload["facets"][0]["facetConstraints"] = [{"slug": "food"}]
    requested_pages = []
    fail = True

    def respond(request):
        p = deepcopy(payload)
        if "categorySlug" in request.url.params:
            page = int(request.url.params["page"])
            requested_pages.append(page)
            if page == 2 and fail:
                return httpx.Response(503)
            p["pagination"].update(page=page, totalPages=2, totalResultCount=8)
        return httpx.Response(200, json=p)

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        result = sync_catalog(tmp_path, db, client, "461766", "85567", 10, 0, NOW)
        assert result["status"] == "failed"
        assert result["pages_completed"] == 1
        assert ObservationRepository(db).query(source=SOURCE)["total"] == 4
        assert (
            sync_catalog(tmp_path, db, client, "461766", "85567", now=NOW)["status"] == "cooldown"
        )
        fail = False
        result = sync_catalog(
            tmp_path, db, client, "461766", "85567", 10, 0, NOW + timedelta(hours=7)
        )
        assert result["status"] == "completed"
        assert requested_pages == [1, 2, 2]


def test_search_cap_is_reported_as_failure_not_full_coverage(tmp_path, db, payload):
    payload["pagination"].update(totalResultCount=10000, totalPages=250)
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    ) as c:
        result = sync_catalog(tmp_path, db, c, "461766", "85567", 10, 0, NOW)
    assert result["status"] == "failed"
    assert "cap" in result["reason"]
    assert result["pages_completed"] == 0
    assert ObservationRepository(db).query(source=SOURCE)["total"] == 0
