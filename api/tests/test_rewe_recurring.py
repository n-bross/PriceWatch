import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from pricewatch_api.main import create_app
from pricewatch_api.observations import ObservationRepository
from pricewatch_api.rewe_recurring import SOURCE, parse_page, sync

NOW = datetime(2026, 10, 4, 17, tzinfo=UTC)


@pytest.fixture
def payload():
    return json.loads((Path(__file__).parent / "fixtures/rewe-shop.json").read_text())


def test_actual_response_keeps_pickup_context_bonus_and_unknown_start(payload):
    entries, pages = parse_page(payload, "461766", "85567", NOW, 1)
    assert pages == 15
    assert [p["price_cents"] for p in entries] == [17, 199, 222, 111]
    assert entries[0]["ean"] == "28003199"
    assert entries[3]["bonus_credit_cents"] == 15
    assert entries[3]["price_cents"] == 111  # Bonus is future credit, not a price deduction.
    assert entries[0]["valid_until"] == "2026-10-10"
    assert all(p["valid_from"] is None for p in entries)
    assert all(p["scope"] == "store_channel" and p["channel"] == "pickup" for p in entries)
    assert all(p["store_id"] == "461766" and p["price_date"] == "2026-10-04" for p in entries)


@pytest.mark.parametrize("change", ["market", "channel", "page", "currency", "price", "url"])
def test_unconfirmed_or_invalid_prices_are_rejected(payload, change):
    if change == "market":
        payload["search"]["marketCode"] = "other"
    elif change == "channel":
        payload["search"]["serviceTypes"] = ["DELIVERY"]
    elif change == "page":
        payload["pagination"]["page"] = 2
    elif change == "url":
        payload["_embedded"]["products"][0]["_links"]["detail"]["href"] = "https://example.org"
    else:
        pricing = payload["_embedded"]["products"][0]["_embedded"]["articles"][0]["_embedded"][
            "listing"
        ]["pricing"]
        pricing["currency" if change == "currency" else "currentRetailPrice"] = (
            "USD" if change == "currency" else 1.99
        )
    with pytest.raises(ValueError):
        parse_page(payload, "461766", "85567", NOW, 1)


def test_invalid_barcode_is_not_replaced_with_article_number(payload):
    payload["_embedded"]["products"][0]["_embedded"]["articles"][0]["gtin"] = "invalid"
    entries, _ = parse_page(payload, "461766", "85567", NOW, 1)
    assert entries[0]["ean"] is None


def test_paginated_import_is_visible_as_observations_and_cools_down(tmp_path, payload):
    app = create_app(f"sqlite:///{tmp_path / 'db'}", "test")
    app.state.db.initialize()
    requests = []

    def respond(request):
        requests.append(request)
        page = int(request.url.params["page"])
        payload["pagination"].update(page=page, totalPages=2)
        payload["_embedded"]["products"][0]["id"] = f"page-{page}"
        return httpx.Response(200, json=payload)

    with httpx.Client(transport=httpx.MockTransport(respond)) as http:
        result = sync(tmp_path, app.state.db, http, "461766", "85567", now=NOW)
        assert result["status"] == "imported"
        assert result["processed"] == 8
        assert result["pages"] == 2
        assert (
            sync(tmp_path, app.state.db, http, "461766", "85567", now=NOW)["status"] == "cooldown"
        )
    assert len(requests) == 2
    with TestClient(app) as client:
        items = client.get("/v1/price-observations", params={"source": SOURCE}).json()["items"]
        assert items
        assert all(p["channel"] == "pickup" for p in items)
        assert client.get("/v1/prices").json()["total"] == 0
        comparison = client.get("/v1/compare", params={"q": "Bonduelle", "include_history": True})
        assert comparison.status_code == 200
        assert comparison.json()["items"][0]["prices"][0]["channel"] == "pickup"


@pytest.mark.parametrize("failure", ["limit", "later_http_error", "repeated_page", "empty"])
def test_incomplete_fetch_never_publishes_partial_results(tmp_path, payload, failure):
    app = create_app(f"sqlite:///{tmp_path / 'db'}", "test")
    app.state.db.initialize()

    def respond(request):
        page = int(request.url.params["page"])
        payload["pagination"].update(page=page, totalPages=2)
        if failure == "limit":
            payload["pagination"]["totalPages"] = 21
        elif failure == "empty":
            payload["_embedded"]["products"] = []
        elif page == 2:
            if failure == "later_http_error":
                return httpx.Response(503)
            payload["pagination"]["page"] = 1
        return httpx.Response(200, json=payload)

    with httpx.Client(transport=httpx.MockTransport(respond)) as http:
        result = sync(tmp_path, app.state.db, http, "461766", "85567", now=NOW)
    assert result["status"] == "failed"
    assert ObservationRepository(app.state.db).query(source=SOURCE)["total"] == 0


def test_rate_limit_retains_existing_prices_and_prevents_immediate_retry(tmp_path, payload):
    app = create_app(f"sqlite:///{tmp_path / 'db'}", "test")
    app.state.db.initialize()
    entries, _ = parse_page(payload, "461766", "85567", NOW, 1)
    ObservationRepository(app.state.db).save(entries)
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(429, headers={"Retry-After": "86400"})

    with httpx.Client(transport=httpx.MockTransport(respond)) as http:
        assert sync(tmp_path, app.state.db, http, "461766", "85567", now=NOW)["status"] == "failed"
        result = sync(
            tmp_path, app.state.db, http, "461766", "85567", now=NOW + timedelta(minutes=15)
        )
        assert result["status"] == "cooldown"
    assert len(requests) == 1
    assert ObservationRepository(app.state.db).query(source=SOURCE)["total"] == 4
