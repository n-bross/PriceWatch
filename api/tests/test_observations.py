import csv
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

from pricewatch_api.main import create_app
from pricewatch_api.observations import ObservationRepository, cents, retry_delay, sync_dm


def test_dataset_prices_preserve_date_unknown_scope_and_invalid_barcode(tmp_path):
    path = tmp_path / "prices.csv"
    columns = [
        "retailer",
        "product_name",
        "ean_barcode",
        "category",
        "price_eur",
        "price_date",
        "collected_at",
        "source",
    ]
    with path.open("w") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerow(
            dict(
                zip(
                    columns,
                    [
                        "REWE",
                        "Apfel",
                        "4006381333931",
                        "Obst",
                        "1.29",
                        "2025-09-09",
                        "2026-08-30",
                        "open-prices",
                    ],
                )
            )
        )
        writer.writerow(
            dict(
                zip(
                    columns,
                    [
                        "ALDI",
                        "Milch",
                        "internal123",
                        "Milch",
                        "0.99",
                        "",
                        "2026-08-30",
                        "marktguru-offers",
                    ],
                )
            )
        )
    with TestClient(create_app(f"sqlite:///{tmp_path / 'db'}", "test")) as client:
        repo = ObservationRepository(client.app.state.db)
        assert repo.import_dataset(path)["processed"] == 2
        repo.import_dataset(path)
        data = client.get("/v1/price-observations").json()
        assert data["total"] == 2
        dated, undated = data["items"]
        assert dated["price_date"] == "2025-09-09"
        assert dated["date_status"] == "historical"
        assert dated["scope"] == "unknown"
        assert dated["current_price_verified"] is False
        assert dated["valid_until"] is None
        assert undated["ean"] is None
        assert undated["raw_barcode"] == "internal123"
        assert undated["date_status"] == "undated"
        assert (
            client.get("/v1/price-observations", params={"postal_code": "85567"}).json()["total"]
            == 0
        )
        # These observations never become current local offers.
        assert client.get("/v1/prices").json()["total"] == 0
        assert client.get("/v1/price-observations", params={"ean": "20000004"}).status_code == 422
        assert client.get("/v1/price-observations", params={"q": "%"}).json()["total"] == 0


def test_money_rejects_invalid_prices():
    assert cents("1,29") == 129
    for price in ["NaN", "Infinity", "-1", "1000001"]:
        with pytest.raises(ValueError):
            cents(price)


def test_dm_resume_and_retry_after_do_not_restart_or_duplicate_prices(tmp_path, monkeypatch):
    monkeypatch.setattr("pricewatch_api.observations.time.sleep", lambda _: None)
    requests = []
    blocked = True

    def respond(request):
        requests.append(int(request.url.params["currentPage"]))
        if requests[-1] == 1 and blocked:
            return httpx.Response(429, headers={"Retry-After": "7200"})
        item = {
            "dan": requests[-1] + 1,
            "gtin": "4006381333931",
            "title": "Testprodukt",
            "brandName": "Marke",
            "tileData": {"trackingData": {"price": 1.29}},
        }
        return httpx.Response(
            200, json={"products": [item], "count": 2, "totalPages": 2, "facets": []}
        )

    with TestClient(create_app(f"sqlite:///{tmp_path / 'db'}", "test")) as app_client:
        repo = ObservationRepository(app_client.app.state.db)
        with httpx.Client(transport=httpx.MockTransport(respond)) as client:
            first = sync_dm(client, repo, tmp_path)
            assert first["phase"] == "cooldown"
            assert first["next_page"] == 1
            assert first["unique_articles"] == 1
            assert datetime.fromisoformat(first["next_retry_at"]) > datetime.now(UTC) + timedelta(
                minutes=119
            )
            sync_dm(client, repo, tmp_path)
            assert requests == [0, 1]  # cooldown performs no additional request
            checkpoint = tmp_path / "dm-progress.json"
            state = json.loads(checkpoint.read_text())
            state["next_retry_at"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
            checkpoint.write_text(json.dumps(state))
            blocked = False
            second = sync_dm(client, repo, tmp_path)
            assert requests == [0, 1, 1]  # retry failed page, not the root
            assert second["phase"] == "completed"
            assert second["unique_articles"] == 2
            assert repo.query()["total"] == 2
            sync_dm(client, repo, tmp_path)
            assert requests == [0, 1, 1]  # completed cycle waits a day


def test_retry_after_http_date_and_invalid_value():
    from email.utils import format_datetime

    assert retry_delay("12") == 300
    assert retry_delay("invalid") == 3600
    future = format_datetime(datetime.now(UTC) + timedelta(hours=2), usegmt=True)
    assert 7190 < retry_delay(future) <= 7200
