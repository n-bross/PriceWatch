import json
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pricewatch_api.barcodes import barcode_scope, valid_ean
from pricewatch_api.catalog import articles
from pricewatch_api.comparison import register_comparison_routes
from pricewatch_api.database import Database, metadata, prices
from pricewatch_api.observations import observations


def test_netto_display_alias_does_not_include_ambiguous_chain(client):
    api, db = client
    from pricewatch_api.observations import ObservationRepository

    ObservationRepository(db).save(
        [
            {
                "source": "fixture",
                "retailer": retailer,
                "name": "Testprodukt",
                "ean": "4008400401829",
                "price_cents": price,
                "price_date": date.today().isoformat(),
                "scope": "unknown",
            }
            for retailer, price in [("Netto", 99), ("Netto Marken-Discount", 199)]
        ]
    )
    response = api.get("/v1/compare", params={"retailer": "Netto Marken-Discount"})
    assert response.status_code == 200
    assert [p["price_cents"] for p in response.json()["items"][0]["prices"]] == [199]
    coverage = api.get("/v1/coverage").json()
    netto = next(r for r in coverage["retailers"] if r["id"] == "netto")
    assert netto["price_count"] == 1


@pytest.fixture
def client(tmp_path):
    db_path = tmp_path / "test_comparison.db"
    db = Database(f"sqlite:///{db_path}")
    metadata.create_all(db.engine)

    app = FastAPI()
    register_comparison_routes(app, db)
    return TestClient(app), db


def test_exact_global_ean_merges_across_retailers(client):
    client, db = client
    today = date.today()
    nutella_ean = "4008400401829"

    with db.engine.begin() as conn:
        conn.execute(
            prices.insert().values(
                id="price_rewe_nutella",
                source="rewe_scraper",
                retailer="rewe",
                source_product_id="rewe_n1",
                name="Nutella 450g Glas",
                normalized_name="nutella 450g glas",
                brand="Ferrero",
                ean=nutella_ean,
                kind="regular",
                price_cents=329,
                currency="EUR",
                valid_from=today,
                valid_until=today + timedelta(days=7),
                scope="chain_advertised",
                requires_membership=False,
                source_url="https://rewe.de/nutella",
                observed_at=datetime.now(UTC),
                is_listed=True,
            )
        )
        conn.execute(
            prices.insert().values(
                id="price_lidl_nutella",
                source="lidl_scraper",
                retailer="lidl",
                source_product_id="lidl_n1",
                name="Ferrero Nutella Nuss-Nougat-Creme",
                normalized_name="ferrero nutella nuss-nougat-creme",
                brand="Ferrero",
                ean=nutella_ean,
                kind="offer",
                price_cents=299,
                currency="EUR",
                valid_from=today,
                valid_until=today + timedelta(days=7),
                scope="chain_advertised",
                requires_membership=False,
                source_url="https://lidl.de/nutella",
                observed_at=datetime.now(UTC),
                is_listed=True,
            )
        )

    response = client.get("/v1/compare", params={"ean": nutella_ean})
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    item = data["items"][0]
    assert item["identity"] == "global_ean"
    assert item["ean"] == nutella_ean
    assert len(item["prices"]) == 2
    retailers = {p["retailer"] for p in item["prices"]}
    assert retailers == {"rewe", "lidl"}
    assert item["prices"][0]["price_cents"] == 299
    assert item["prices"][1]["price_cents"] == 329


def test_never_merge_missing_ean_identical_names(client):
    client, db = client
    today = date.today()

    with db.engine.begin() as conn:
        conn.execute(
            prices.insert().values(
                id="price_rewe_ban",
                source="rewe_scraper",
                retailer="rewe",
                source_product_id="rewe_b1",
                name="Bananen lose",
                normalized_name="bananen lose",
                ean=None,
                kind="offer",
                price_cents=129,
                currency="EUR",
                valid_from=today,
                valid_until=today + timedelta(days=5),
                scope="chain_advertised",
                requires_membership=False,
                source_url="https://rewe.de/bananen",
                observed_at=datetime.now(UTC),
                is_listed=True,
            )
        )
        conn.execute(
            prices.insert().values(
                id="price_netto_ban",
                source="netto_scraper",
                retailer="netto",
                source_product_id="netto_b1",
                name="Bananen lose",
                normalized_name="bananen lose",
                ean=None,
                kind="offer",
                price_cents=119,
                currency="EUR",
                valid_from=today,
                valid_until=today + timedelta(days=5),
                scope="chain_advertised",
                requires_membership=False,
                source_url="https://netto.de/bananen",
                observed_at=datetime.now(UTC),
                is_listed=True,
            )
        )

    response = client.get("/v1/compare", params={"q": "Bananen"})
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    keys = {item["key"] for item in data["items"]}
    assert "article:rewe:rewe_b1" in keys
    assert "article:netto:netto_b1" in keys
    for item in data["items"]:
        assert item["identity"] == "retailer_article"
        assert item["ean"] is None
        assert len(item["prices"]) == 1


def test_restricted_circulation_barcode_requires_retailer(client):
    client, db = client
    today = date.today()
    rcn_code = "28012344"
    assert valid_ean(rcn_code)
    assert barcode_scope(rcn_code) == "restricted_circulation"

    with db.engine.begin() as conn:
        conn.execute(
            prices.insert().values(
                id="price_rewe_rcn",
                source="rewe_scraper",
                retailer="rewe",
                source_product_id="rewe_r1",
                name="Rinderhackfleisch 500g",
                normalized_name="rinderhackfleisch 500g",
                ean=rcn_code,
                kind="regular",
                price_cents=499,
                currency="EUR",
                valid_from=today,
                valid_until=today + timedelta(days=7),
                scope="chain_advertised",
                requires_membership=False,
                source_url="https://rewe.de/hack",
                observed_at=datetime.now(UTC),
                is_listed=True,
            )
        )
        conn.execute(
            prices.insert().values(
                id="price_lidl_rcn",
                source="lidl_scraper",
                retailer="lidl",
                source_product_id="lidl_r1",
                name="Gouda jung am Stueck",
                normalized_name="gouda jung am stueck",
                ean=rcn_code,
                kind="regular",
                price_cents=349,
                currency="EUR",
                valid_from=today,
                valid_until=today + timedelta(days=7),
                scope="chain_advertised",
                requires_membership=False,
                source_url="https://lidl.de/gouda",
                observed_at=datetime.now(UTC),
                is_listed=True,
            )
        )

    resp_no_retailer = client.get("/v1/compare", params={"ean": rcn_code})
    assert resp_no_retailer.status_code == 422

    resp_rewe = client.get("/v1/compare", params={"ean": rcn_code, "retailer": "rewe"})
    assert resp_rewe.status_code == 200
    data_rewe = resp_rewe.json()
    assert data_rewe["total"] == 1
    item_rewe = data_rewe["items"][0]
    assert item_rewe["identity"] == "restricted_circulation"
    assert item_rewe["key"] == f"rcn:rewe:{rcn_code}"
    assert item_rewe["name"] == "Rinderhackfleisch 500g"

    resp_lidl = client.get("/v1/compare", params={"ean": rcn_code, "retailer": "lidl"})
    assert resp_lidl.status_code == 200
    data_lidl = resp_lidl.json()
    assert data_lidl["total"] == 1
    item_lidl = data_lidl["items"][0]
    assert item_lidl["identity"] == "restricted_circulation"
    assert item_lidl["key"] == f"rcn:lidl:{rcn_code}"
    assert item_lidl["name"] == "Gouda jung am Stueck"


def test_regression_real_uppercase_displayname_retailer_rewe(client):
    client, db = client
    today = date.today()

    with db.engine.begin() as conn:
        conn.execute(
            prices.insert().values(
                id="price_rewe_display_upper",
                source="rewe_scraper",
                retailer="REWE",
                source_product_id="art_rewe_upper",
                name="Bio Apfel REWE",
                normalized_name="bio apfel rewe",
                ean=None,
                kind="regular",
                price_cents=199,
                currency="EUR",
                valid_from=today,
                valid_until=today + timedelta(days=7),
                scope="chain_advertised",
                requires_membership=False,
                source_url="https://rewe.de/apfel",
                observed_at=datetime.now(UTC),
                is_listed=True,
            )
        )
        conn.execute(
            observations.insert().values(
                id="obs_rewe_display_upper",
                source="german_supermarket_prices",
                retailer="REWE",
                ean=None,
                name="Bio Apfel REWE Observation",
                normalized_name="bio apfel rewe observation",
                price_cents=189,
                price_date=today.isoformat(),
                postal_code=None,
                store_id=None,
                payload_json=json.dumps(
                    {
                        "source_product_id": "art_rewe_upper",
                        "source_url": "https://example.com/rewe/apfel",
                        "kind": "offer",
                        "price_date": today.isoformat(),
                    }
                ),
            )
        )

    resp_lower = client.get("/v1/compare", params={"retailer": "rewe"})
    assert resp_lower.status_code == 200
    data = resp_lower.json()
    assert data["total"] == 1
    item = data["items"][0]
    assert item["key"] == "article:rewe:art_rewe_upper"
    assert len(item["prices"]) == 2

    resp_upper = client.get("/v1/compare", params={"retailer": "REWE"})
    assert resp_upper.status_code == 200
    assert resp_upper.json()["total"] == 1


def test_ambiguous_retailer_filter_rejected_exact_alias_accepted(client):
    client, _ = client
    resp_aldi = client.get("/v1/compare", params={"retailer": "aldi"})
    assert resp_aldi.status_code == 422

    resp_netto = client.get("/v1/compare", params={"retailer": "netto"})
    assert resp_netto.status_code == 422

    resp_sued = client.get("/v1/compare", params={"retailer": "ALDI Süd"})
    assert resp_sued.status_code == 200

    resp_nd = client.get("/v1/compare", params={"retailer": "Netto Marken-Discount"})
    assert resp_nd.status_code == 200


def test_native_and_observation_shared_source_product_id(client):
    client, db = client
    today = date.today().isoformat()

    with db.engine.begin() as conn:
        conn.execute(
            prices.insert().values(
                id="native_gurke",
                source="rewe_scraper",
                retailer="rewe",
                source_product_id="art_gurke_100",
                name="Salatgurke regional",
                normalized_name="salatgurke regional",
                ean=None,
                kind="regular",
                price_cents=99,
                currency="EUR",
                valid_from=date.today(),
                valid_until=date.today() + timedelta(days=7),
                scope="store",
                postal_code="10115",
                store_id="rewe_store_1",
                requires_membership=False,
                source_url="https://rewe.de/gurke",
                observed_at=datetime.now(UTC),
                is_listed=True,
            )
        )
        conn.execute(
            observations.insert().values(
                id="obs_gurke",
                source="german_supermarket_prices",
                retailer="rewe",
                ean=None,
                name="Salatgurke regional Observation",
                normalized_name="salatgurke regional observation",
                price_cents=89,
                price_date=today,
                postal_code="10115",
                store_id="rewe_store_1",
                payload_json=json.dumps(
                    {
                        "source_product_id": "art_gurke_100",
                        "source_url": "https://example.com/obs/gurke",
                        "kind": "offer",
                        "price_date": today,
                        "conditions_text": "2 for 1 special",
                        "scope": "store",
                    }
                ),
            )
        )

    resp = client.get("/v1/compare", params={"q": "Salatgurke"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    item = data["items"][0]
    assert item["key"] == "article:rewe:art_gurke_100"
    assert len(item["prices"]) == 2
    prices_cents = [p["price_cents"] for p in item["prices"]]
    assert prices_cents == [89, 99]
    obs_p = next(p for p in item["prices"] if p["price_cents"] == 89)
    assert obs_p["conditions"] == "2 for 1 special"


def test_compact_json_membership_handling(client):
    client, db = client
    today = date.today().isoformat()

    with db.engine.begin() as conn:
        conn.execute(
            observations.insert().values(
                id="obs_member_compact",
                source="german_supermarket_prices",
                retailer="penny",
                ean=None,
                name="Penny Card Loyalty Coffee",
                normalized_name="penny card loyalty coffee",
                price_cents=399,
                price_date=today,
                postal_code=None,
                store_id=None,
                payload_json='{"source_product_id":"p_mem_1","requires_membership":true}',
            )
        )

    resp_no_mem = client.get("/v1/compare", params={"q": "Loyalty Coffee"})
    assert resp_no_mem.status_code == 200
    assert resp_no_mem.json()["total"] == 0

    resp_mem = client.get("/v1/compare", params={"q": "Loyalty Coffee", "include_membership": True})
    assert resp_mem.status_code == 200
    assert resp_mem.json()["total"] == 1
    assert resp_mem.json()["items"][0]["prices"][0]["requires_membership"] is True


def test_mapped_ean_ambiguous_across_store_choose_not_arbitrary(client):
    client, db = client
    today = date.today()

    with db.engine.begin() as conn:
        conn.execute(
            articles.insert().values(
                retailer="rewe",
                source_product_id="yogurt_var",
                store_id="store_berlin_1",
                ean="4001234567890",
                source_url="https://rewe.de/art1",
                note=None,
                observed_at=datetime.now(UTC),
            )
        )
        conn.execute(
            articles.insert().values(
                retailer="rewe",
                source_product_id="yogurt_var",
                store_id="store_munich_2",
                ean="4009876543210",
                source_url="https://rewe.de/art2",
                note=None,
                observed_at=datetime.now(UTC),
            )
        )
        conn.execute(
            prices.insert().values(
                id="price_rewe_chain_yogurt",
                source="rewe_scraper",
                retailer="rewe",
                source_product_id="yogurt_var",
                name="Bio Fruchtjoghurt 150g",
                normalized_name="bio fruchtjoghurt 150g",
                ean=None,
                kind="regular",
                price_cents=79,
                currency="EUR",
                valid_from=today,
                valid_until=today + timedelta(days=7),
                scope="chain_advertised",
                requires_membership=False,
                source_url="https://rewe.de/yogurt",
                observed_at=datetime.now(UTC),
                is_listed=True,
            )
        )
        conn.execute(
            prices.insert().values(
                id="price_rewe_berlin_yogurt",
                source="rewe_scraper",
                retailer="rewe",
                source_product_id="yogurt_var",
                name="Bio Fruchtjoghurt 150g Berlin",
                normalized_name="bio fruchtjoghurt 150g berlin",
                ean=None,
                kind="regular",
                price_cents=79,
                currency="EUR",
                valid_from=today,
                valid_until=today + timedelta(days=7),
                scope="store",
                postal_code="10115",
                store_id="store_berlin_1",
                requires_membership=False,
                source_url="https://rewe.de/yogurt_b",
                observed_at=datetime.now(UTC),
                is_listed=True,
            )
        )

    resp_chain = client.get("/v1/compare", params={"q": "Fruchtjoghurt 150g"})
    assert resp_chain.status_code == 200
    items = resp_chain.json()["items"]
    chain_item = next(it for it in items if it["key"] == "article:rewe:yogurt_var")
    assert chain_item["identity"] == "retailer_article"
    assert chain_item["ean"] is None

    berlin_item = next(it for it in items if it["key"] == "ean:4001234567890")
    assert berlin_item["identity"] == "global_ean"
    assert berlin_item["ean"] == "4001234567890"


def test_native_offers_older_7_days_status_stale_consistently(client):
    client, db = client
    today = date.today()
    offer_ean = "4005555666677"

    with db.engine.begin() as conn:
        conn.execute(
            prices.insert().values(
                id="price_old_offer",
                source="rewe_scraper",
                retailer="rewe",
                source_product_id="old_off_1",
                name="Butter Angebot 250g",
                normalized_name="butter angebot 250g",
                ean=offer_ean,
                kind="offer",
                price_cents=149,
                currency="EUR",
                valid_from=today - timedelta(days=5),
                valid_until=today + timedelta(days=3),
                scope="chain_advertised",
                requires_membership=False,
                source_url="https://rewe.de/butter",
                observed_at=datetime.now(UTC) - timedelta(days=9),
                is_listed=True,
            )
        )

    resp_default = client.get("/v1/compare", params={"ean": offer_ean})
    assert resp_default.status_code == 200
    assert resp_default.json()["total"] == 0

    resp_history = client.get("/v1/compare", params={"ean": offer_ean, "include_history": True})
    assert resp_history.status_code == 200
    data = resp_history.json()
    assert data["total"] == 1
    price_entry = data["items"][0]["prices"][0]
    assert price_entry["status"] == "stale"


def test_coverage_endpoint_reads_packaged_file_and_preserves_dynamic_counts(tmp_path):
    coverage_file = tmp_path / "retailer_coverage.json"
    mock_cov = {
        "checked_at": "2025-01-01T12:00:00+00:00",
        "retailers": [
            {
                "id": "rewe",
                "name": "REWE",
                "full_price_list_downloaded": True,
                "price_status": "full_assortment_online",
                "reason": "Comprehensive online assortment catalog verified",
                "attempts": [
                    {
                        "method": "GET",
                        "url": "https://rewe.de/shop/",
                        "http_status": 200,
                        "reason": "api_success",
                    }
                ],
                "downloaded_pdfs": ["https://rewe.de/catalog.pdf"],
            }
        ],
    }
    coverage_file.write_text(json.dumps(mock_cov), encoding="utf-8")

    import pricewatch_api.comparison as comp_mod

    orig_candidates = comp_mod._load_coverage_data

    def mocked_load():
        return mock_cov["checked_at"], {"rewe": mock_cov["retailers"][0]}

    comp_mod._load_coverage_data = mocked_load

    try:
        db_path = tmp_path / "test_cov.db"
        db = Database(f"sqlite:///{db_path}")
        metadata.create_all(db.engine)

        today = date.today()
        with db.engine.begin() as conn:
            conn.execute(
                prices.insert().values(
                    id="cov_price_1",
                    source="rewe_scraper",
                    retailer="REWE",
                    source_product_id="p_cov_1",
                    name="Bio Milch",
                    normalized_name="bio milch",
                    ean="4001111222233",
                    kind="regular",
                    price_cents=119,
                    currency="EUR",
                    valid_from=today,
                    valid_until=today + timedelta(days=7),
                    scope="chain_advertised",
                    requires_membership=False,
                    source_url="https://rewe.de/milch",
                    observed_at=datetime.now(UTC),
                    is_listed=True,
                )
            )

        app = FastAPI()
        register_comparison_routes(app, db)
        test_client = TestClient(app)

        resp = test_client.get("/v1/coverage")
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["checked_at"] == "2025-01-01T12:00:00+00:00"

        rewe = next(r for r in payload["retailers"] if r["id"] == "rewe")
        assert rewe["full_price_list_downloaded"] is True
        assert rewe["price_status"] == "full_assortment_online"
        assert rewe["reason"] == "Comprehensive online assortment catalog verified"
        assert len(rewe["attempts"]) == 1
        assert rewe["downloaded_pdfs"] == ["https://rewe.de/catalog.pdf"]
        assert rewe["price_count"] == 1
        assert rewe["ean_count"] == 1

        other = next(r for r in payload["retailers"] if r["id"] == "lidl")
        assert other["price_status"] == "unknown"
        assert other["attempts"] == []
        assert other["full_price_list_downloaded"] is False
    finally:
        comp_mod._load_coverage_data = orig_candidates


def test_recent_observation_survives_midnight_without_claiming_current(client):
    api, db = client
    from zoneinfo import ZoneInfo

    from pricewatch_api.observations import ObservationRepository

    yesterday = datetime.now(ZoneInfo("Europe/Berlin")).date() - timedelta(days=1)
    ObservationRepository(db).save(
        [
            {
                "source": "fixture",
                "retailer": "Combi",
                "name": "Midnight fixture",
                "ean": "4008400401829",
                "price_cents": 199,
                "price_date": yesterday.isoformat(),
                "scope": "online",
            }
        ]
    )
    result = api.get("/v1/compare", params={"ean": "4008400401829"}).json()
    assert result["total"] == 1
    assert result["items"][0]["prices"][0]["status"] == "recently_observed"
    assert result["items"][0]["prices"][0]["price_date"] == yesterday.isoformat()


def test_recent_window_excludes_expired_future_and_old_observations(client):
    api, db = client
    from zoneinfo import ZoneInfo

    from pricewatch_api.observations import ObservationRepository

    today = datetime.now(ZoneInfo("Europe/Berlin")).date()
    base = {
        "source": "fixture",
        "retailer": "Combi",
        "ean": "4008400401829",
        "name": "Window fixture",
        "scope": "online",
    }
    ObservationRepository(db).save(
        [
            {**base, "price_cents": 100, "price_date": (today - timedelta(days=7)).isoformat()},
            {**base, "price_cents": 200, "price_date": (today - timedelta(days=8)).isoformat()},
            {**base, "price_cents": 300, "price_date": (today + timedelta(days=1)).isoformat()},
            {
                **base,
                "price_cents": 400,
                "price_date": today.isoformat(),
                "valid_until": (today - timedelta(days=1)).isoformat(),
            },
            {
                **base,
                "price_cents": 500,
                "price_date": today.isoformat(),
                "valid_from": (today + timedelta(days=1)).isoformat(),
            },
        ]
    )
    data = api.get("/v1/compare", params={"ean": base["ean"]}).json()
    assert [p["price_cents"] for p in data["items"][0]["prices"]] == [100]
    data = api.get("/v1/compare", params={"ean": base["ean"], "include_history": True}).json()
    assert len(data["items"][0]["prices"]) == 5


def test_latest_recent_snapshot_keeps_store_channel_and_card_context(client):
    api, db = client
    from zoneinfo import ZoneInfo

    from pricewatch_api.observations import ObservationRepository

    today = datetime.now(ZoneInfo("Europe/Berlin")).date()
    base = {
        "source": "fixture",
        "retailer": "Combi",
        "ean": "4008400401829",
        "name": "Snapshot fixture",
        "scope": "online",
        "price_date": today.isoformat(),
    }
    ObservationRepository(db).save(
        [
            {**base, "price_cents": 100, "price_date": (today - timedelta(days=1)).isoformat()},
            {**base, "price_cents": 200},
            {**base, "price_cents": 300, "store_id": "another-store", "scope": "store"},
            {**base, "price_cents": 400, "requires_membership": True},
            {**base, "price_cents": 500, "channel": "delivery"},
        ]
    )
    params = {"ean": base["ean"], "include_membership": True}
    data = api.get("/v1/compare", params=params).json()
    assert [p["price_cents"] for p in data["items"][0]["prices"]] == [200, 300, 400, 500]
    data = api.get("/v1/compare", params={**params, "include_history": True}).json()
    assert len(data["items"][0]["prices"]) == 5
