from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from pricewatch_api.main import create_app
from pricewatch_api.sources import SourceError

AUTH = {"Authorization": "Bearer test-token"}


@pytest.fixture
def client(tmp_path):
    app = create_app(f"sqlite:///{tmp_path / 'prices.db'}", "test-token")
    with TestClient(app) as client:
        yield client


def price(**overrides):
    today = datetime.now(UTC).date()
    return {
        "retailer": "rewe",
        "source_product_id": "apple-1",
        "name": "Äpfel Elstar",
        "kind": "offer",
        "price_cents": 199,
        "deposit_cents": 0,
        "package_label": "2 kg",
        "unit_price_cents": "99.50",
        "unit_price_unit": "kg",
        "valid_from": str(today),
        "valid_until": str(today + timedelta(days=6)),
        "scope": "chain_advertised",
        "source_url": "https://www.rewe.de/angebote/",
        "observed_at": datetime.now(UTC).isoformat(),
        **overrides,
    }


def ingest(client, items):
    return client.post("/v1/imports", headers=AUTH, json={"source": "test_feed", "prices": items})


def test_retailers_and_empty_catalog(client):
    assert client.get("/health").json() == {"status": "ok"}
    assert {"rewe", "penny", "netto_dog", "tegut"} <= {
        r["id"] for r in client.get("/v1/retailers").json()["items"]
    }
    assert client.get("/v1/prices").json()["total"] == 0
    assert client.get("/openapi.json").status_code == 200
    assert all(
        r["price_count"] == r["flyer_page_count"] == 0
        for r in client.get("/v1/retailers").json()["items"]
    )


def test_retailer_counts_show_actual_current_data(client):
    from datetime import timedelta

    ingest(
        client,
        [
            price(),
            price(source_product_id="app", requires_membership=True),
            price(
                source_product_id="expired",
                valid_from=str(datetime.now(UTC).date() - timedelta(days=2)),
                valid_until=str(datetime.now(UTC).date() - timedelta(days=1)),
            ),
        ],
    )
    retailers = {r["id"]: r for r in client.get("/v1/retailers").json()["items"]}
    assert retailers["rewe"]["price_count"] == retailers["rewe"]["offer_count"] == 1
    assert retailers["rewe"]["mode"] == "import_only"
    assert retailers["penny"]["price_count"] == 0


def test_import_search_pagination_and_money(client):
    assert (
        ingest(
            client,
            [
                price(),
                price(retailer="netto", price_cents=149),
                price(retailer="aldi_nord", kind="regular", price_cents=229),
            ],
        ).status_code
        == 200
    )
    page = client.get("/v1/prices", params={"q": "apfel", "limit": 1}).json()
    assert page["total"] == 3
    assert page["items"][0]["retailer"] == "netto"
    assert page["items"][0]["checkout_price_cents"] == 149
    assert page["items"][0]["unit_price_cents"] == "99.50"
    assert client.get("/v1/offers").json()["total"] == 2
    assert client.get("/v1/prices", params={"retailer": "rewe"}).json()["total"] == 1
    assert client.get("/v1/prices", params={"q": "%"}).json()["total"] == 0


def test_idempotence_updates_and_older_observations(client):
    first = price()
    assert ingest(client, [first, first]).json()["processed"] == 1
    original_id = client.get("/v1/offers").json()["items"][0]["id"]
    assert ingest(client, [price(price_cents=169)]).status_code == 200
    assert (
        ingest(
            client,
            [
                price(
                    price_cents=299, observed_at=(datetime.now(UTC) - timedelta(days=1)).isoformat()
                )
            ],
        ).status_code
        == 200
    )
    page = client.get("/v1/offers").json()
    assert page["total"] == 1
    assert page["items"][0]["price_cents"] == 169
    assert page["items"][0]["id"] == original_id


def test_date_boundaries_freshness_and_membership(client):
    today = datetime.now(UTC).date()
    ingest(
        client,
        [
            price(source_product_id="today", valid_until=str(today)),
            price(
                source_product_id="expired",
                valid_from=str(today - timedelta(days=3)),
                valid_until=str(today - timedelta(days=1)),
            ),
            price(source_product_id="future", valid_from=str(today + timedelta(days=1))),
            price(
                source_product_id="stale",
                observed_at=(datetime.now(UTC) - timedelta(days=8)).isoformat(),
            ),
            price(source_product_id="member", requires_membership=True),
        ],
    )
    assert client.get("/v1/offers", params={"on": str(today)}).json()["total"] == 1
    assert (
        client.get(
            "/v1/offers", params={"on": str(today), "include_membership": True, "max_age_days": 10}
        ).json()["total"]
        == 3
    )


def test_location_never_leaks_other_store_prices(client):
    ingest(
        client,
        [
            price(),
            price(scope="postal_code", postal_code="10115"),
            price(scope="postal_code", postal_code="80331"),
            price(scope="store", store_id="berlin-1", postal_code="10115"),
            price(scope="store", store_id="berlin-2", postal_code="10115"),
        ],
    )
    assert client.get("/v1/prices").json()["total"] == 5
    page = client.get("/v1/prices", params={"postal_code": "10115"}).json()
    assert page["total"] == 2
    page = client.get("/v1/prices", params={"postal_code": "10115", "store_id": "berlin-1"}).json()
    assert page["total"] == 3
    assert {p["store_id"] for p in page["items"]} == {None, "berlin-1"}


def test_deposit_and_exact_ean(client):
    ingest(
        client,
        [
            price(name="Barcode-Testartikel", deposit_cents=25, ean="4006381333931"),
            price(source_product_id="unknown-deposit", deposit_cents=None),
        ],
    )
    row = client.get("/v1/prices", params={"ean": "4006381333931"}).json()["items"][0]
    assert row["checkout_price_cents"] == 224
    row = client.get("/v1/prices", params={"q": "Elstar"}).json()["items"][0]
    assert row["checkout_price_cents"] is None


def test_ean_validation_and_leading_zero_roundtrip(client):
    assert ingest(client, [price(ean="4006381333932")]).status_code == 422
    assert ingest(client, [price(ean="04006381333931")]).status_code == 200
    row = client.get("/v1/prices", params={"ean": "04006381333931"}).json()["items"][0]
    assert row["ean"] == "04006381333931"
    assert client.get("/v1/prices", params={"ean": "4006381333931"}).json()["total"] == 0


@pytest.mark.parametrize(
    "change",
    [
        {"price_cents": -1},
        {"price_cents": 1.5},
        {"price_cents": True},
        {"valid_until": "2000-01-01"},
        {"scope": "store"},
        {"scope": "postal_code"},
        {"postal_code": "12"},
        {"store_id": "unexpected"},
        {"unit_price_unit": None},
        {"observed_at": "2026-01-01T12:00:00"},
        {"name": " "},
        {"observed_at": (datetime.now(UTC) + timedelta(days=1)).isoformat()},
    ],
)
def test_invalid_batch_writes_nothing(client, change):
    assert ingest(client, [price(), price(**change)]).status_code == 422
    assert client.get("/v1/prices").json()["total"] == 0


def test_authentication_and_reserved_source(client):
    batch = {"source": "test_feed", "prices": [price()]}
    assert client.post("/v1/imports", json=batch).status_code == 401
    assert client.post("/v1/sources/aldi_nord/sync").status_code == 401
    assert (
        client.post("/v1/imports", headers=AUTH, json={**batch, "source": "aldi_nord"}).status_code
        == 422
    )


def test_no_key_disables_writes(tmp_path):
    with TestClient(create_app(f"sqlite:///{tmp_path / 'db'}", "")) as client:
        assert client.post("/v1/sources/aldi_nord/sync").status_code == 503


def test_failed_sync_preserves_catalog_and_records_error(client, monkeypatch):
    import pricewatch_api.main as main

    monkeypatch.setattr(
        main,
        "fetch_aldi",
        lambda: [main.ImportBatch(source="feed", prices=[price(retailer="aldi_nord")]).prices[0]],
    )
    assert client.post("/v1/sources/aldi_nord/sync", headers=AUTH).status_code == 200

    def fail():
        raise SourceError("ALDI returned HTTP 403")

    monkeypatch.setattr(main, "fetch_aldi", fail)
    assert client.post("/v1/sources/aldi_nord/sync", headers=AUTH).status_code == 502
    assert client.get("/v1/offers").json()["total"] == 1
    run = client.get("/v1/sources").json()["items"][0]["run"]
    assert run["status"] == "error"
    assert run["last_success"] is not None


def test_sync_removes_withdrawn_offers_without_removing_other_sources(client, monkeypatch):
    import pricewatch_api.main as main

    ingest(client, [price()])
    items = main.ImportBatch(
        source="feed",
        prices=[
            price(retailer="aldi_nord", source_product_id="a"),
            price(retailer="aldi_nord", source_product_id="b"),
        ],
    ).prices
    monkeypatch.setattr(main, "fetch_aldi", lambda: items)
    client.post("/v1/sources/aldi_nord/sync", headers=AUTH)
    assert client.get("/v1/offers").json()["total"] == 3
    monkeypatch.setattr(main, "fetch_aldi", lambda: [items[1]])
    client.post("/v1/sources/aldi_nord/sync", headers=AUTH)
    assert client.get("/v1/offers").json()["total"] == 2


@pytest.mark.parametrize(
    "params", [{"limit": 101}, {"offset": -1}, {"retailer": "unknown"}, {"postal_code": "ABC"}]
)
def test_query_validation(client, params):
    assert client.get("/v1/prices", params=params).status_code == 422
