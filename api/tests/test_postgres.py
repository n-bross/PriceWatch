import os
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, text
from sqlalchemy.exc import ProgrammingError

from pricewatch_api.database import prices, runs
from pricewatch_api.main import create_app


@pytest.mark.skipif(
    not os.getenv("PRICEWATCH_TEST_DATABASE_URL"),
    reason="Disposable PostgreSQL database not configured",
)
def test_postgres_migration_import_upsert_search_and_rls():
    app = create_app(os.environ["PRICEWATCH_TEST_DATABASE_URL"], "test-token")
    db = app.state.db
    with db.engine.begin() as conn:
        conn.execute(delete(prices))
        conn.execute(delete(runs))
    today = datetime.now(UTC).date()
    item = {
        "retailer": "netto",
        "source_product_id": "test-id",
        "name": "Äpfel",
        "kind": "offer",
        "price_cents": 149,
        "scope": "chain_advertised",
        "valid_from": str(today),
        "valid_until": str(today + timedelta(days=2)),
        "source_url": "https://www.netto-online.de/",
        "observed_at": datetime.now(UTC).isoformat(),
    }
    with TestClient(app) as client:
        for amount in [149, 129]:
            item.update(price_cents=amount, observed_at=datetime.now(UTC).isoformat())
            assert (
                client.post(
                    "/v1/imports",
                    headers={"Authorization": "Bearer test-token"},
                    json={"source": "test_feed", "prices": [item]},
                ).status_code
                == 200
            )
        page = client.get("/v1/offers", params={"q": "apfel"}).json()
        assert page["total"] == 1
        assert page["items"][0]["price_cents"] == 129
        assert client.get("/health").status_code == 200
        retailer = next(
            row for row in client.get("/v1/retailers").json()["items"] if row["id"] == "netto"
        )
        assert retailer["price_count"] == 1
        product = {
            "ean": "4006381333931",
            "name": "Synthetic product identity fixture",
            "countries": ["en:germany"],
            "source_url": "https://example.org/identity-evidence",
        }
        assert (
            client.post(
                "/v1/products/import",
                headers={"Authorization": "Bearer test-token"},
                json={"products": [product]},
            ).status_code
            == 200
        )
        assert (
            client.put(
                "/v1/retailer-products",
                headers={"Authorization": "Bearer test-token"},
                json={
                    "retailer": "netto",
                    "source_product_id": "test-id",
                    "ean": product["ean"],
                    "identity_confirmed": True,
                    "source_url": product["source_url"],
                    "observed_at": datetime.now(UTC).isoformat(),
                },
            ).status_code
            == 200
        )
        row = client.get("/v1/prices", params={"ean": product["ean"]}).json()["items"][0]
        assert row["ean_origin"] == "confirmed_mapping"
        assert client.get("/v1/products/" + product["ean"]).json()["source"] == "verified_import"
        with pytest.raises(ProgrammingError):
            with db.engine.begin() as conn:
                conn.execute(text("set local role anon"))
                conn.execute(text("select * from public.price_catalog"))
        for table in [
            "product_catalog",
            "product_retailer_articles",
            "product_catalog_sources",
            "external_price_observations",
        ]:
            with pytest.raises(ProgrammingError):
                with db.engine.begin() as conn:
                    conn.execute(text("set local role anon"))
                    conn.execute(text(f"select * from public.{table}"))
