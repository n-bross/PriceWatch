import json
from datetime import UTC, datetime

from pricewatch_api.database import Database
from pricewatch_api.import_status import import_status, summarize
from pricewatch_api.observations import ObservationRepository


def test_failed_refresh_does_not_change_reported_evidence_date(tmp_path):
    db = Database("sqlite:///:memory:")
    db.initialize()
    ObservationRepository(db).save(
        [
            {
                "source": "edeka_public_offers",
                "retailer": "EDEKA",
                "name": "Apfel",
                "price_cents": 199,
                "price_date": "2026-10-01",
            }
        ]
    )
    checkpoint = tmp_path / "edeka-offers/status.json"
    checkpoint.parent.mkdir()
    checkpoint.write_text(json.dumps({"status": "failed", "reason": "SECRET PRIVATE URL"}))
    result = import_status(db, tmp_path, datetime(2026, 10, 4, tzinfo=UTC))
    edeka = next(x for x in result["items"] if x["id"] == "edeka")
    assert edeka["status"] == "failed"
    assert edeka["latest_price_date"] == "2026-10-01"
    assert edeka["observations"] == 1
    assert "SECRET" not in json.dumps(result)
    assert next(x for x in result["items"] if x["id"] == "rewe")["status"] == "manual"


def test_completed_cycle_and_cooldown_are_distinct(tmp_path):
    path = tmp_path / "state.json"
    now = datetime(2026, 10, 4, tzinfo=UTC)
    state = {
        "complete": True,
        "completed": ["private_url"],
        "products": ["sku"],
        "pending": [],
        "errors": {"private_url": "error"},
        "completed_at_epoch": now.timestamp(),
    }
    path.write_text(json.dumps(state))
    summary = summarize(path, "bulk", now)
    assert summary["status"] == "completed_with_errors"
    assert summary["cycle_products"] == 1
    assert "private_url" not in json.dumps(summary)
    state.update(complete=False, retry_after_epoch=now.timestamp() + 3600)
    path.write_text(json.dumps(state))
    assert summarize(path, "bulk", now)["status"] == "cooldown"


def test_missing_and_malformed_state_do_not_break_status(tmp_path):
    now = datetime.now(UTC)
    path = tmp_path / "state.json"
    assert summarize(path, "bulk", now)["status"] == "unknown"
    for content in ["{broken", "[]", '{"completed": null}', "null"]:
        path.write_text(content)
        assert summarize(path, "bulk", now)["status"] == "unreadable"


def test_status_aggregation_uses_covering_index_on_existing_database(tmp_path):
    from sqlalchemy import text

    db = Database(f"sqlite:///{tmp_path / 'legacy.db'}")
    db.initialize()
    # Simulate an installation made before the optimization, then upgrade in place.
    with db.engine.begin() as conn:
        conn.execute(text("DROP INDEX IF EXISTS external_prices_source_date"))
    db.initialize()
    db.initialize()  # Repeated startup must be safe.
    with db.engine.connect() as conn:
        plan = conn.execute(
            text(
                "EXPLAIN QUERY PLAN SELECT source, count(*), max(price_date) "
                "FROM external_price_observations GROUP BY source"
            )
        ).all()
    assert any("COVERING INDEX external_prices_source_date" in row[-1] for row in plan)


def test_rewe_catalog_progress_is_visible_without_exposing_raw_checkpoint(tmp_path):
    db = Database("sqlite:///:memory:")
    db.initialize()
    path = tmp_path / "rewe-shop/461766-85567/catalog.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "status": "in_progress",
                "article_ids": ["a", "b"],
                "pages_completed": 2,
                "categories": ["food", "drinks"],
                "completed_categories": ["food"],
                "reason": "PRIVATE",
                "pending": [{"private": "URL"}],
            }
        )
    )
    result = import_status(db, tmp_path)
    item = next(x for x in result["items"] if x["id"] == "rewe_shop")
    assert item["cycle_products"] == 2
    assert item["categories_completed"] == 1
    assert item["status"] == "in_progress"
    assert "PRIVATE" not in json.dumps(result)
    assert "pending" not in item
