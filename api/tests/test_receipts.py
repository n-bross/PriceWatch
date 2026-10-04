import shutil
from datetime import UTC, datetime, timedelta

import pymupdf
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from pricewatch_api.main import create_app
from pricewatch_api.models import PriceInput
from pricewatch_api.receipts import extract_receipt, parse_receipt
from pricewatch_api.tracker import refresh_requests

AUTH = {"Authorization": "Bearer test-token"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PRICEWATCH_RECEIPT_DIR", str(tmp_path / "receipts"))
    monkeypatch.setenv("PRICEWATCH_FLYER_DIR", str(tmp_path / "flyers"))
    with TestClient(create_app(f"sqlite:///{tmp_path / 'db'}", "test-token")) as client:
        yield client


def receipt_pdf():
    text = (
        f"PENNY\n{datetime.now(UTC):%d.%m.%Y}\nOREO Kekse 1,29 A\nPfand 0,25\nSumme 1,54\nBar 2,00"
    )
    with pymupdf.open() as doc:
        doc.new_page().insert_text((40, 50), text, fontsize=16)
        return doc.tobytes()


def upload(client, **params):
    return client.post(
        "/v1/receipts",
        headers=AUTH,
        params={"postal_code": "85625", "store_id": "565668", **params},
        files={"file": ("bon.pdf", receipt_pdf(), "application/pdf")},
    )


def add_price(client, **overrides):
    today = datetime.now(UTC).date()
    item = PriceInput(
        **{
            "retailer": "penny",
            "source_product_id": "oreo",
            "name": "OREO Kekse",
            "kind": "offer",
            "price_cents": 129,
            "package_label": "154 g",
            "scope": "store",
            "store_id": "565668",
            "postal_code": "85625",
            "valid_from": today,
            "valid_until": today + timedelta(days=3),
            "observed_at": datetime.now(UTC),
            "source_url": "https://www.penny.de/angebote",
            **overrides,
        }
    )
    client.app.state.db.import_prices("test", [item])
    return next(
        p
        for p in client.get("/v1/prices", params={"include_membership": True}).json()["items"]
        if p["source_product_id"] == item.source_product_id
    )


def reviewed(receipt, catalog_id, **overrides):
    line = {
        **receipt["lines"][0],
        "catalog_price_id": catalog_id,
        "identity_confirmed": True,
        "needs_quantity_review": False,
        **overrides,
    }
    return {**receipt["metadata"], "lines": [line], "confirmed": True}


def test_auth_upload_review_queue_and_no_overwrite(client):
    price = add_price(client)
    assert client.post("/v1/receipts").status_code == 401
    assert client.get("/v1/receipts").status_code == 401
    assert client.get("/tools").status_code == 200
    receipt = upload(client).json()
    assert receipt["metadata"]["retailer"] == "penny"
    assert len(receipt["lines"]) == 1
    assert receipt["comparisons"][0]["status"] == "provisional_match"
    path = f"/v1/receipts/{receipt['id']}/review"
    assert client.get(f"/v1/receipts/{receipt['id']}").status_code == 401
    assert (
        client.put(path, headers=AUTH, json=reviewed(receipt, price["id"])).json()["comparisons"][
            0
        ]["status"]
        == "match"
    )
    result = client.put(
        path, headers=AUTH, json=reviewed(receipt, price["id"], paid_total_cents=149)
    ).json()
    assert result["comparisons"][0]["difference_cents"] == 20
    assert result["comparisons"][0]["status"] == "mismatch"
    assert result["recheck"]["status"] == "queued"
    assert client.get("/v1/prices").json()["items"][0]["price_cents"] == 129
    assert client.get("/v1/receipts", headers=AUTH).json()["items"][0]["id"] == receipt["id"]
    assert client.delete(f"/v1/receipts/{receipt['id']}", headers=AUTH).status_code == 200
    assert client.get(f"/v1/receipts/{receipt['id']}", headers=AUTH).status_code == 404
    with client.app.state.db.engine.connect() as conn:
        assert conn.scalar(select(refresh_requests.c.receipt_id)) is None


def test_quantities_and_weight(client):
    price = add_price(client)
    receipt = upload(client).json()
    path = f"/v1/receipts/{receipt['id']}/review"
    assert (
        client.put(
            path,
            headers=AUTH,
            json=reviewed(receipt, price["id"], paid_total_cents=258, quantity="2"),
        ).json()["comparisons"][0]["status"]
        == "match"
    )
    weight = add_price(
        client,
        source_product_id="loose",
        name="Tomaten",
        price_cents=699,
        package_label="1 kg (lose)",
        unit_price_cents="699",
        unit_price_unit="kg",
    )
    response = client.put(
        path,
        headers=AUTH,
        json=reviewed(
            receipt,
            weight["id"],
            name="Tomaten",
            paid_total_cents=175,
            quantity="0.250",
            quantity_unit="kg",
        ),
    ).json()
    assert response["comparisons"][0]["status"] == "match"
    assert response["comparisons"][0]["expected_total_cents"] == 175


def test_wrong_store_expiry_and_membership(client):
    price = add_price(client, requires_membership=True)
    receipt = upload(client, store_id="other").json()
    assert receipt["comparisons"][0]["status"] == "not_found"
    review = reviewed(receipt, price["id"])
    path = f"/v1/receipts/{receipt['id']}/review"
    assert (
        client.put(path, headers=AUTH, json=review).json()["comparisons"][0]["status"]
        == "invalid_selection"
    )
    review.update(store_id="565668")
    assert (
        client.put(path, headers=AUTH, json=review).json()["comparisons"][0]["status"]
        == "invalid_selection"
    )
    review["lines"][0]["membership_used"] = True
    assert client.put(path, headers=AUTH, json=review).json()["comparisons"][0]["status"] == "match"
    review["purchase_date"] = str(datetime.now(UTC).date() - timedelta(days=1))
    assert (
        client.put(path, headers=AUTH, json=review).json()["comparisons"][0]["status"]
        == "invalid_selection"
    )


def test_chain_advertisements_and_fuzzy_names(client):
    price = add_price(client, scope="chain_advertised", store_id=None, postal_code=None)
    receipt = upload(client).json()
    path = f"/v1/receipts/{receipt['id']}/review"
    assert (
        client.put(path, headers=AUTH, json=reviewed(receipt, price["id"])).json()["comparisons"][
            0
        ]["status"]
        == "advertised_match"
    )
    assert (
        client.put(
            path,
            headers=AUTH,
            json=reviewed(receipt, price["id"], name="OREO Keks", identity_confirmed=False),
        ).json()["comparisons"][0]["status"]
        == "needs_review"
    )


def test_parser_totals_deposits_discounts_and_quantities():
    draft, excluded = parse_receipt(
        "ALDI\nOREO Kekse 2,58 A\n2 x 1,29\nPFAND 0,25\nRABATT -0,20\nSUMME 2,63\nBAR 3,00"
    )
    assert draft.retailer is None
    assert len(draft.lines) == 1
    assert draft.lines[0].paid_total_cents == 258
    assert draft.lines[0].needs_quantity_review
    assert len(excluded) == 5


def test_invalid_file_and_future_date(client):
    assert (
        client.post(
            "/v1/receipts", headers=AUTH, files={"file": ("bad.png", b"not an image", "image/png")}
        ).status_code
        == 422
    )
    assert (
        upload(client, purchase_date=str(datetime.now(UTC).date() + timedelta(days=1))).status_code
        == 422
    )
    assert client.get("/v1/receipts", headers=AUTH).json()["items"] == []


@pytest.mark.skipif(not shutil.which("tesseract"), reason="Local Tesseract not installed")
def test_real_png_scan_ocr():
    with pymupdf.open(stream=receipt_pdf(), filetype="pdf") as doc:
        image = doc[0].get_pixmap(dpi=150).tobytes("png")
    text, method = extract_receipt(image)
    assert method == "tesseract_ocr"
    proposal, _ = parse_receipt(text)
    assert proposal.retailer == "penny"
    assert any("OREO" in line.name and line.paid_total_cents == 129 for line in proposal.lines)


def test_extra_discount_is_saved_separately_and_catalog_checked_before_discount(client):
    price = add_price(client, price_cents=899)
    receipt = upload(client).json()
    path = f"/v1/receipts/{receipt['id']}/review"
    payload = reviewed(
        receipt,
        price["id"],
        paid_total_cents=629,
        discount={"original_total_cents": 899, "percent": "30", "kind": "sticker"},
    )
    response = client.put(path, headers=AUTH, json=payload)
    assert response.status_code == 200
    comparison = response.json()["comparisons"][0]
    assert comparison["status"] == "match"
    assert comparison["difference_cents"] == 0
    assert comparison["discount_cents"] == 270
    assert comparison["paid_total_cents"] == 629
    assert comparison["compared_total_cents"] == 899
    saved = client.get(f"/v1/receipts/{receipt['id']}", headers=AUTH).json()
    assert saved["lines"][0]["discount"]["kind"] == "sticker"
    assert client.get("/v1/prices").json()["items"][0]["price_cents"] == 899
    payload["lines"][0]["discount"] = {"original_total_cents": 999, "kind": "coupon"}
    assert (
        client.put(path, headers=AUTH, json=payload).json()["comparisons"][0]["status"]
        == "mismatch"
    )


def test_discount_percent_consistency_and_weighted_original_total(client):
    price = add_price(client, price_cents=899, unit_price_cents="899", unit_price_unit="kg")
    receipt = upload(client).json()
    path = f"/v1/receipts/{receipt['id']}/review"
    payload = reviewed(
        receipt,
        price["id"],
        quantity="0.8",
        quantity_unit="kg",
        paid_total_cents=503,
        discount={"original_total_cents": 719, "percent": "30", "kind": "other"},
    )
    response = client.put(path, headers=AUTH, json=payload)
    assert response.status_code == 200
    assert response.json()["comparisons"][0]["status"] == "match"
    payload["lines"][0]["paid_total_cents"] = 600
    assert client.put(path, headers=AUTH, json=payload).status_code == 422
    payload["lines"][0]["discount"] = {"original_total_cents": 500}
    assert client.put(path, headers=AUTH, json=payload).status_code == 422
