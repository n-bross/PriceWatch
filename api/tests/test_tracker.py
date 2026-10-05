from datetime import UTC, date, datetime, timedelta

import httpx
import pymupdf
from fastapi.testclient import TestClient
from sqlalchemy import select

from pricewatch_api.database import Database, prices
from pricewatch_api.flyers import FlyerInfo
from pricewatch_api.main import create_app
from pricewatch_api.models import PriceInput
from pricewatch_api.sources import SourceError
from pricewatch_api.tracker import Tracker, refresh_requests
from pricewatch_api.web_sources import penny_upcoming_categories


def price(**changes):
    return PriceInput(
        **{
            "retailer": "penny",
            "source_product_id": "milk",
            "name": "Milch",
            "kind": "offer",
            "price_cents": 99,
            "scope": "store",
            "store_id": "one",
            "postal_code": "85567",
            "valid_from": date.today(),
            "valid_until": date.today() + timedelta(days=6),
            "observed_at": datetime.now(UTC),
            "source_url": "https://www.penny.de/angebote",
            **changes,
        }
    )


def test_versions_ignore_identical_older_and_record_withdrawal(tmp_path):
    db = Database(f"sqlite:///{tmp_path / 'db'}")
    db.initialize()
    first = price()
    db.import_prices("test", [first], snapshot=True)
    with db.engine.connect() as conn:
        price_id = conn.scalar(select(prices.c.id))
    db.import_prices("test", [first.model_copy(update={"observed_at": datetime.now(UTC)})])
    assert len(db.price_history(price_id)) == 1
    db.import_prices("test", [price(price_cents=79)])
    db.import_prices(
        "test", [price(price_cents=59, observed_at=first.observed_at - timedelta(seconds=1))]
    )
    assert [r["price"]["price_cents"] for r in db.price_history(price_id)] == [79, 99]
    db.import_prices("test", [price(source_product_id="butter")], snapshot=True)
    assert db.price_history(price_id)[0]["event"] == "withdrawn"


def test_tracker_change_state_and_error_preserves_catalog(tmp_path, monkeypatch):
    db = Database(f"sqlite:///{tmp_path / 'db'}")
    db.initialize()

    def sync(db, source, postal_code):
        db.import_prices(source, [price(retailer=source)])
        return {"processed": 1}

    monkeypatch.setattr("pricewatch_api.tracker.sync_source", sync)
    tracker = Tracker(db)
    assert tracker.sync("aldi_nord")
    assert tracker.state()[0]["status"] == "changed"
    assert tracker.sync("aldi_nord")
    assert tracker.state()[0]["status"] == "unchanged"

    def fail(*args):
        raise SourceError("HTTP 403")

    monkeypatch.setattr("pricewatch_api.tracker.sync_source", fail)
    assert not tracker.sync("aldi_nord")
    assert tracker.state()[0]["status"] == "error"
    with db.engine.connect() as conn:
        assert conn.scalar(select(prices.c.price_cents)) == 99


def test_conditional_watch_and_blocked_status(tmp_path, monkeypatch):
    db = Database(f"sqlite:///{tmp_path / 'db'}")
    db.initialize()
    captured = []

    def handle(request):
        captured.append(request.headers)
        return httpx.Response(
            304 if request.headers.get("if-none-match") else 200,
            text='<a href="week.pdf">KW40</a>',
            headers={"ETag": "v1"},
        )

    real_client = httpx.Client
    monkeypatch.setattr(
        "pricewatch_api.tracker.httpx.Client",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handle)),
    )
    tracker = Tracker(db)
    result = tracker.watch_page("edeka", "https://www.edeka.de/angebote/", None)
    assert result[3] == "changed_unparsed"
    old = {"fingerprint": result[2], "etag": "v1", "last_modified": None}
    assert tracker.watch_page("edeka", result[1], old)[3] == "unchanged"
    assert captured[-1]["if-none-match"] == "v1"
    monkeypatch.setattr(
        "pricewatch_api.tracker.httpx.Client",
        lambda **kwargs: real_client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(403, text="WAF Challenge Bot protection")
            )
        ),
    )
    blocked = tracker.watch_page("edeka", result[1], old)
    assert blocked[3] == "blocked"
    assert "WAF Challenge" in blocked[4]


def test_lidl_cache_skips_unchanged_download(tmp_path, monkeypatch):
    db = Database(f"sqlite:///{tmp_path / 'db'}")
    db.initialize()
    monkeypatch.setenv("PRICEWATCH_FLYER_DIR", str(tmp_path / "flyers"))
    info = FlyerInfo(
        title="Week",
        retailer="lidl",
        source_url="https://assets.leaflets.schwarz/week.pdf",
        valid_from=date.today(),
        valid_until=date.today(),
        scope="chain_advertised",
    )
    with pymupdf.open() as doc:
        doc.new_page().insert_text((40, 50), "Spezi im Wochenprospekt, Angebot 0.79 EUR.")
        content = doc.tobytes()
    downloads = []
    monkeypatch.setattr("pricewatch_api.flyer_sources.discover_lidl_flyer", lambda on=None: info)
    monkeypatch.setattr(
        "pricewatch_api.flyer_sources.download_lidl_pdf",
        lambda url: downloads.append(url) or content,
    )
    real_client = httpx.Client
    monkeypatch.setattr(
        "pricewatch_api.tracker.httpx.Client",
        lambda **kwargs: real_client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, headers={"ETag": "same"})
            )
        ),
    )
    tracker = Tracker(db)
    assert tracker.sync_lidl()
    assert tracker.sync_lidl()
    assert len(downloads) == 1
    assert tracker.state()[0]["status"] == "unchanged"


def test_next_week_penny_dates():
    html = (
        '<div data-next-week="2026-41"></div><div class="tabs__content--next-week">'
        '<section data-category-name="food">Nächste Woche Mo-Sa</section></div>'
    )
    assert penny_upcoming_categories(html) == (
        "2026-41",
        [("food", date(2026, 10, 5), date(2026, 10, 10))],
    )
    assert penny_upcoming_categories(html.replace("Mo-Sa", "demnächst"))[1] == []


def test_queued_receipt_rechecked_after_refresh(tmp_path, monkeypatch):
    monkeypatch.setenv("PRICEWATCH_RECEIPT_DIR", str(tmp_path / "receipts"))
    monkeypatch.setattr("pricewatch_api.tracker.WATCH_URLS", {})
    monkeypatch.setattr(Tracker, "sync_lidl", lambda self, *args: True)
    with TestClient(create_app(f"sqlite:///{tmp_path / 'db'}", "test")) as client:
        db = client.app.state.db
        db.import_prices("test", [price()])
        price_id = client.get("/v1/prices").json()["items"][0]["id"]
        with pymupdf.open() as doc:
            doc.new_page().insert_text(
                (40, 50), f"PENNY\n{date.today():%d.%m.%Y}\nMilch 0,79 A\nSumme 0,79"
            )
            pdf = doc.tobytes()
        auth = {"Authorization": "Bearer test"}
        receipt = client.post(
            "/v1/receipts",
            headers=auth,
            params={"store_id": "one", "postal_code": "85567"},
            files={"file": ("bon.pdf", pdf)},
        ).json()
        review = {
            **receipt["metadata"],
            "confirmed": True,
            "lines": [
                {**receipt["lines"][0], "catalog_price_id": price_id, "identity_confirmed": True}
            ],
        }
        assert (
            client.put(f"/v1/receipts/{receipt['id']}/review", headers=auth, json=review).json()[
                "recheck"
            ]["status"]
            == "queued"
        )

        def sync(self, source, postal_code=None):
            if source == "penny":
                db.import_prices("test", [price(price_cents=79)])
            return True

        monkeypatch.setattr(Tracker, "sync", sync)
        assert Tracker(db).run()["status"] == "ok"
        result = client.get(f"/v1/receipts/{receipt['id']}", headers=auth).json()
        assert result["comparisons"][0]["status"] == "match"
        assert result["recheck"]["status"] == "resolved"
        with db.engine.connect() as conn:
            assert conn.scalar(select(refresh_requests.c.status)) == "resolved"
