from datetime import UTC, datetime

from fastapi.testclient import TestClient

from pricewatch_api.main import create_app


def test_browser_prices_require_auth_and_context_and_remain_channel_specific(tmp_path):
    with TestClient(create_app(f"sqlite:///{tmp_path / 'db'}", "test")) as client:
        batch = {
            "store_id": "461766",
            "postal_code": "85567",
            "channel": "pickup",
            "captured_at": datetime.now(UTC).isoformat(),
            "context_confirmed": True,
            "products": [
                {
                    "source_product_id": "item",
                    "name": "Testprodukt",
                    "ean": "4006381333931",
                    "price_cents": 129,
                    "source_url": "https://www.rewe.de/shop/p/test/123",
                }
            ],
        }
        assert client.post("/v1/rewe/browser-prices", json=batch).status_code == 401
        auth = {"Authorization": "Bearer test"}
        assert (
            client.post(
                "/v1/rewe/browser-prices", json={**batch, "context_confirmed": False}, headers=auth
            ).status_code
            == 422
        )
        response = client.post("/v1/rewe/browser-prices", json=batch, headers=auth)
        assert response.status_code == 200
        assert response.json()["processed"] == 1
        client.post("/v1/rewe/browser-prices", json=batch, headers=auth)
        data = client.get("/v1/price-observations", params={"source": "rewe_browser"}).json()
        assert data["total"] == 1
        assert data["items"][0]["channel"] == "pickup"
        assert data["items"][0]["scope"] == "store_channel"
        assert data["items"][0]["valid_until"] is None
        assert client.get("/v1/prices").json()["total"] == 0
        assert client.get("/v1/products/4006381333931").json()["price_observations"]["total"] == 1
        batch["products"][0]["source_url"] = "https://rewe.de.example.org/"
        assert client.post("/v1/rewe/browser-prices", json=batch, headers=auth).status_code == 422
        assert client.get("/rewe-import").status_code == 200
        assert client.get("/rewe-export.js").status_code == 200


def test_bonus_credit_is_preserved_without_reducing_price_and_market_must_match(tmp_path):
    with TestClient(create_app(f"sqlite:///{tmp_path / 'db'}", "test")) as client:
        batch = {
            "store_id": "461766",
            "postal_code": "85567",
            "channel": "advertised",
            "captured_at": datetime.now(UTC).isoformat(),
            "context_confirmed": True,
            "products": [
                {
                    "source_product_id": "2363484",
                    "source_store_id": "461766",
                    "name": "Rügenwalder Vegane Mühlen Cordon bleu",
                    "price_cents": 249,
                    "bonus_credit_cents": 20,
                    "requires_membership": False,
                    "valid_from": "2026-09-28",
                    "valid_until": "2026-10-04",
                    "source_offer_week": "2026/40",
                    "kind": "offer",
                    "source_url": "https://www.rewe.de/angebote/grafing/461766/rewe-leonhardstr-5-a/",
                }
            ],
        }
        auth = {"Authorization": "Bearer test"}
        assert client.post("/v1/rewe/browser-prices", json=batch, headers=auth).status_code == 200
        item = client.get("/v1/price-observations", params={"source": "rewe_browser"}).json()[
            "items"
        ][0]
        assert item["price_cents"] == 249
        assert item["bonus_credit_cents"] == 20
        assert item["valid_until"] == "2026-10-04"
        assert item["ean"] is None
        offer = client.get("/v1/offers", params={"store_id": "461766", "on": "2026-10-02"}).json()
        assert offer["total"] == 1
        assert offer["items"][0]["price_cents"] == 249
        batch["store_id"] = "999999"
        assert client.post("/v1/rewe/browser-prices", json=batch, headers=auth).status_code == 422
