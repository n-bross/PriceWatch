import csv
import gzip
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from pricewatch_api.catalog import ProductInput, ProductRepository
from pricewatch_api.database import prices
from pricewatch_api.main import create_app

AUTH = {"Authorization": "Bearer test-token"}
EAN = "4006381333931"
OTHER = "96385074"


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(f"sqlite:///{tmp_path / 'db'}", "test-token")) as client:
        yield client


def product(**overrides):
    return {
        "ean": EAN,
        "name": "Testprodukt Äpfel",
        "brand": "Testmarke",
        "package_label": "2 kg",
        "countries": ["en:germany"],
        "source_url": "https://example.org/evidence",
        **overrides,
    }


def offer(**overrides):
    today = datetime.now(UTC).date()
    return {
        "retailer": "penny",
        "source_product_id": "item-42",
        "name": "Äpfel",
        "kind": "regular",
        "price_cents": 299,
        "scope": "store",
        "store_id": "store-a",
        "postal_code": "85567",
        "valid_from": str(today),
        "valid_until": str(today + timedelta(days=7)),
        "source_url": "https://example.org/evidence",
        "observed_at": datetime.now(UTC).isoformat(),
        **overrides,
    }


def mapping(**overrides):
    return {
        "retailer": "penny",
        "source_product_id": "item-42",
        "store_id": "store-a",
        "ean": EAN,
        "source_url": "https://example.org/evidence",
        "identity_confirmed": True,
        "observed_at": datetime.now(UTC).isoformat(),
        **overrides,
    }


def seed_products(client):
    response = client.post(
        "/v1/products/import", headers=AUTH, json={"products": [product(), product(ean=OTHER)]}
    )
    assert response.status_code == 200


def test_product_import_search_provenance_and_auth(client):
    assert client.post("/v1/products/import", json={"products": [product()]}).status_code == 401
    seed_products(client)
    row = client.get("/v1/products", params={"q": "apfel", "limit": 1}).json()["items"][0]
    assert row["availability"] == "not_verified"
    assert row["source"] == "verified_import"
    assert client.get("/v1/products", params={"q": "%"}).json()["total"] == 0
    assert client.get("/v1/products/" + EAN).json()["retailer_articles"] == []
    assert client.get("/v1/products/status").json()["product_count"] == 2
    assert client.get("/v1/products/1234567890123").status_code == 404
    assert (
        client.post(
            "/v1/products/import", headers=AUTH, json={"products": [product(ean="4006381333932")]}
        ).status_code
        == 422
    )
    assert client.get("/products").status_code == 200


def test_mapping_confirmation_store_isolation_and_raw_price_preservation(client):
    assert client.put("/v1/retailer-products", headers=AUTH, json=mapping()).status_code == 422
    seed_products(client)
    assert client.put("/v1/retailer-products", json=mapping()).status_code == 401
    assert (
        client.put(
            "/v1/retailer-products", headers=AUTH, json=mapping(identity_confirmed=False)
        ).status_code
        == 422
    )
    client.post(
        "/v1/imports",
        headers=AUTH,
        json={
            "source": "test_feed",
            "prices": [offer(), offer(store_id="store-b"), offer(retailer="rewe")],
        },
    )
    assert client.put("/v1/retailer-products", headers=AUTH, json=mapping()).status_code == 200
    rows = client.get("/v1/prices", params={"ean": EAN}).json()["items"]
    assert len(rows) == 1 and rows[0]["store_id"] == "store-a"
    assert rows[0]["ean_origin"] == "confirmed_mapping"
    with client.app.state.db.engine.connect() as conn:
        assert all(ean is None for ean in conn.scalars(select(prices.c.ean)))
    assert (
        client.get("/v1/products/" + EAN + "/prices", params={"kind": "regular"}).json()["total"]
        == 1
    )
    assert (
        client.get("/v1/products/" + EAN + "/prices", params={"kind": "offer"}).json()["total"] == 0
    )
    assert (
        client.get("/v1/products/" + EAN + "/prices", params={"store_id": "store-b"}).json()[
            "total"
        ]
        == 0
    )
    assert (
        client.delete(
            "/v1/retailer-products",
            headers=AUTH,
            params={"retailer": "penny", "source_product_id": "item-42", "store_id": "store-a"},
        ).json()["deleted"]
        == 1
    )
    assert client.get("/v1/prices", params={"ean": EAN}).json()["total"] == 0


def test_source_barcode_and_store_override_win_over_chain_mapping(client):
    seed_products(client)
    client.post(
        "/v1/imports",
        headers=AUTH,
        json={
            "source": "test_feed",
            "prices": [
                offer(),
                offer(store_id="store-b"),
                offer(store_id="store-c", ean=EAN),
                offer(scope="chain_advertised", store_id=None, postal_code=None),
            ],
        },
    )
    client.put("/v1/retailer-products", headers=AUTH, json=mapping(ean=OTHER, store_id=None))
    client.put("/v1/retailer-products", headers=AUTH, json=mapping())
    rows = client.get("/v1/prices", params={"ean": EAN}).json()["items"]
    assert {r["store_id"] for r in rows} == {"store-a", "store-c"}
    assert next(r for r in rows if r["store_id"] == "store-c")["ean_origin"] == "source"
    assert client.get("/v1/prices", params={"ean": OTHER}).json()["total"] == 2
    client.put(
        "/v1/retailer-products",
        headers=AUTH,
        json=mapping(ean=OTHER, observed_at=(datetime.now(UTC) - timedelta(days=2)).isoformat()),
    )
    assert client.get("/v1/prices", params={"ean": EAN}).json()["total"] == 2


def test_bulk_country_filter_checksums_and_correction_protection(client, tmp_path):
    path = tmp_path / "products.tsv.gz"
    rows = [
        {
            "code": EAN,
            "product_name": "Community name",
            "countries_tags": "en:germany,en:france",
            "quantity": "2 kg",
            "brands": "Community brand",
            "stores": "REWE",
            "last_modified_t": "1700000000",
        },
        {"code": OTHER, "product_name": "Not Germany", "countries_tags": "en:france"},
        {
            "code": "4006381333932",
            "product_name": "Invalid checksum",
            "countries_tags": "en:germany",
        },
        {"code": "04006381333931", "product_name": "", "countries_tags": "en:germany"},
    ]
    with gzip.open(path, "wt", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]), delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)
    repo = ProductRepository(client.app.state.db)
    assert repo.import_off_csv(path) == {
        "scanned": 4,
        "germany_tagged": 3,
        "rejected": 2,
        "processed": 1,
    }
    row = client.get("/v1/products/" + EAN).json()
    assert row["source"] == "open_food_facts" and row["attribution"]["license"] == "ODbL-1.0"
    assert row["reported_stores"] == "REWE" and row["retailer_articles"] == []
    repo.upsert([ProductInput(**product(name="Confirmed operator correction"))])
    repo.import_off_csv(path)
    assert client.get("/v1/products/" + EAN).json()["name"] == "Confirmed operator correction"
    assert client.get("/v1/prices").json()["total"] == 0


def test_secondary_dataset_retains_provenance_and_never_publishes_old_prices(client, tmp_path):
    repo = ProductRepository(client.app.state.db)
    repo.upsert(
        [ProductInput(**product(categories=["en:fruit"], brand="Trusted brand"))], "open_food_facts"
    )
    path = tmp_path / "dataset.csv"
    rows = [
        dict(
            ean_barcode=EAN,
            product_name="Unverified variant text",
            retailer="dm",
            category="Angebot · Lebensmittel",
            collected_at="2026-08-30",
            price_eur="1.00",
        ),
        dict(
            ean_barcode=EAN,
            product_name="Another name",
            retailer="REWE",
            category="Lebensmittel",
            collected_at="2026-08-30",
            price_eur="2.00",
        ),
    ]
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    result = repo.import_dataset_products(path)
    assert result["unique_barcodes"] == 1 and result["prices_imported"] == 0
    detail = client.get("/v1/products/" + EAN).json()
    assert detail["name"] == "Testprodukt Äpfel" and detail["brand"] == "Trusted brand"
    assert {r["source"] for r in detail["source_records"]} == {
        "open_food_facts",
        "german_supermarket_prices",
    }
    assert detail["retailer_articles"] == []
    assert client.get("/v1/prices").json()["total"] == 0
    assert (
        client.get("/v1/products", params={"category": "en:fruit", "brand": "trusted"}).json()[
            "total"
        ]
        == 1
    )
    assert client.get("/v1/products", params={"category": "fruit"}).json()["total"] == 0


def test_local_barcode_requires_retailer_for_price_comparison(client):
    code = "27230923"  # Valid check digit, but RCN-8 retailer-local prefix.
    client.post(
        "/v1/imports",
        headers=AUTH,
        json={"source": "test_feed", "prices": [offer(ean=code), offer(ean=code, retailer="rewe")]},
    )
    detail = client.get("/v1/products/" + code).json()
    assert detail["barcode_scope"] == "restricted_circulation"
    assert client.get("/v1/prices", params={"ean": code}).status_code == 422
    assert client.get("/v1/products/" + code + "/prices").status_code == 422
    rows = client.get("/v1/products/" + code + "/prices", params={"retailer": "penny"}).json()[
        "items"
    ]
    assert len(rows) == 1 and rows[0]["retailer"] == "penny"
    assert rows[0]["barcode_scope"] == "restricted_circulation"
