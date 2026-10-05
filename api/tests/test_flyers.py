from datetime import UTC, datetime

import pymupdf
import pytest
from fastapi.testclient import TestClient

from pricewatch_api.main import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PRICEWATCH_FLYER_DIR", str(tmp_path / "flyers"))
    with TestClient(create_app(f"sqlite:///{tmp_path / 'db'}", "test-token")) as client:
        yield client


def pdf():
    with pymupdf.open() as doc:
        doc.new_page().insert_text(
            (40, 50), "Bananen 1.29 EUR pro kg; Spezi 0.79 EUR plus 0.25 EUR Pfand.\nNur mit App."
        )
        doc.new_page()  # A scanned/empty page requires OCR instead of invented text.
        return doc.tobytes()


def upload(client, content=None, **overrides):
    today = str(datetime.now(UTC).date())
    params = {
        "title": "Testprospekt",
        "retailer": "lidl",
        "valid_from": today,
        "valid_until": today,
        "source_url": "https://www.lidl.de/prospekt.pdf",
        **overrides,
    }
    return client.post(
        "/v1/flyers/import",
        headers={"Authorization": "Bearer test-token"},
        params=params,
        files={"file": ("test.pdf", content or pdf(), "application/pdf")},
    )


def test_pdf_search_download_and_no_unverified_prices(client):
    content = pdf()
    result = upload(client, content=content).json()
    assert result["pages"] == 2
    assert result["needs_ocr_pages"] == 1
    assert not result["price_imported"]
    page = client.get("/v1/flyers", params={"q": "bananen"}).json()
    assert page["total"] == 1
    row = page["items"][0]
    assert row["page"] == 1
    assert "1.29" in row["price_candidates"]
    assert row["extraction_status"] == "unverified_text"
    assert client.get(row["pdf_path"].split("#")[0]).content.startswith(b"%PDF")
    assert client.get("/v1/prices").json()["total"] == 0
    assert upload(client, content=content).json()["id"] == result["id"]
    assert client.get("/v1/flyers").json()["total"] == 2


def test_pdf_region_and_metadata_validation(client):
    assert upload(client, scope="regional").status_code == 422
    assert upload(client, scope="regional", region_label="Hessen").status_code == 200
    assert client.get("/v1/flyers", params={"postal_code": "85567"}).json()["total"] == 0
    assert upload(client, valid_until="2000-01-01").status_code == 422
    assert upload(client, content=b"not a pdf").status_code == 422
    assert client.post("/v1/flyers/import").status_code == 401
    assert client.get("/v1/flyers/../../etc/passwd/pdf").status_code == 404


def test_pdf_revision_replaces_search_index_and_preserves_original(client):
    original = upload(client).json()
    with pymupdf.open() as doc:
        doc.new_page().insert_text(
            (40, 50), "Birnen 1.49 EUR pro kg. Neuer aktueller Wochenprospekt."
        )
        revised = upload(client, content=doc.tobytes()).json()
    assert revised["id"] != original["id"]
    assert client.get("/v1/flyers", params={"q": "Bananen"}).json()["total"] == 0
    assert client.get("/v1/flyers", params={"q": "Birnen"}).json()["total"] == 1
    assert client.get("/v1/flyers").json()["total"] == 1
    assert client.get(f"/v1/flyers/{original['id']}/pdf").status_code == 200
