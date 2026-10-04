import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pricewatch_api.main import create_app
from pricewatch_api.sources import SourceError
from pricewatch_api.web_sources import (
    parse_aldi_sued,
    parse_kaufland,
    parse_penny_category,
    penny_categories,
)

FIXTURES = Path(__file__).with_name("fixtures")


def test_penny_real_prices_app_conditions_and_correct_unit_basis():
    items = parse_penny_category(
        json.loads((FIXTURES / "penny-offers.json").read_text()),
        url="https://www.penny.de/.rest/offers/by-category/2026-40/top-angebote",
        valid_from=date(2026, 9, 28),
        valid_until=date(2026, 10, 3),
        observed_at=datetime.now(UTC),
    )
    leerdammer = [p for p in items if "LEERDAMMER" in p.name]
    assert {(p.price_cents, p.requires_membership) for p in leerdammer} == {
        (149, False),
        (129, True),
    }
    butter = next(p for p in items if "Butterkäse" in p.name)
    assert butter.requires_membership
    assert butter.price_cents == 159
    assert butter.unit_price_cents == 1060  # 1193 is the without-app unit price.
    assert butter.deposit_cents is None


def test_penny_category_day_ranges_are_not_guessed():
    html = '<div data-current-week="2026-40"></div><div class="tabs__content--current-week">'
    html += '<section data-category-name="framstag">Diese Woche Fr-Fr</section></div>'
    week, cats = penny_categories(html)
    assert week == "2026-40"
    assert cats == [("framstag", date(2026, 10, 2), date(2026, 10, 2))]
    with pytest.raises(SourceError):
        penny_categories(html.replace("Fr-Fr", "bald"))


def test_kaufland_card_and_multibuy_prices_are_separate():
    items = parse_kaufland((FIXTURES / "kaufland-offers.html").read_text(), datetime.now(UTC))
    assert len(items) == 3  # Two ordinary prices and one separate Card price; no multibuy.
    assert sum(p.requires_membership for p in items) == 1
    assert items[0].price_cents == 399
    assert all(p.scope == "chain_advertised" for p in items)


def test_aldi_sued_explicit_weekly_dates_and_cents():
    items = parse_aldi_sued(
        (FIXTURES / "aldi-sued-weekly.html").read_text(), datetime(2026, 10, 2, tzinfo=UTC)
    )
    assert len(items) == 1
    assert items[0].price_cents == 189
    assert items[0].valid_until == date(2026, 10, 2)  # Holiday week ends Friday.
    assert items[0].unit_price_cents == 95


def test_aldi_sued_loose_weight_price_and_piece_sale_basis():
    items = parse_aldi_sued(
        (FIXTURES / "aldi-sued-sale-units.html").read_text(), datetime(2026, 10, 2, tzinfo=UTC)
    )
    pumpkin = next(p for p in items if "Hokkaido" in p.name)
    assert pumpkin.price_cents == 99
    assert pumpkin.unit_price_unit == "kg"
    assert pumpkin.unit_price_cents == 99
    assert pumpkin.package_label == "1 kg (lose; nach Gewicht)"
    assert "nach Gewicht" in pumpkin.conditions
    cucumber = next(p for p in items if "Gurke" in p.name)
    assert cucumber.package_label == "1 Stück"
    assert cucumber.unit_price_unit == "item"
    assert cucumber.unit_price_cents == 49


def test_postal_area_store_mapping_and_snapshot_isolation(tmp_path):
    from pricewatch_api.models import PriceInput

    with TestClient(create_app(f"sqlite:///{tmp_path / 'db'}", "test-token")) as client:
        db = client.app.state.db
        today = datetime.now(UTC).date()

        def item(store_id, code):
            return PriceInput(
                retailer="penny",
                source_product_id="milk",
                name="Milch",
                kind="offer",
                price_cents=99,
                scope="store",
                store_id=store_id,
                postal_code=code,
                valid_from=today,
                valid_until=today,
                observed_at=datetime.now(UTC),
                source_url="https://www.penny.de/angebote",
            )

        db.import_prices("penny:store:one", [item("one", "85625")], snapshot=True)
        db.import_prices("penny:store:two", [item("two", "85570")], snapshot=True)
        db.save_area_stores(
            "85567",
            "penny",
            [
                {
                    "wwIdent": "one",
                    "marketName": "Glonn",
                    "zipCode": "85625",
                    "streetWithHouseNumber": "Teststraße 1",
                    "city": "Glonn",
                    "latitude": 48,
                    "longitude": 11,
                    "distance_km": 7.28,
                }
            ],
        )
        assert client.get("/v1/offers", params={"postal_code": "85567"}).json()["total"] == 1
        assert client.get("/v1/offers", params={"postal_code": "99999"}).json()["total"] == 0
        assert client.get("/v1/offers").json()["total"] == 2
        assert client.get("/v1/areas/85567/stores").json()["items"][0]["postal_code"] == "85625"
        assert (
            client.post(
                "/v1/sources/rewe/sync", headers={"Authorization": "Bearer test-token"}
            ).status_code
            == 422
        )


def test_penny_percentage_campaign_is_not_a_euro_price():
    items = parse_penny_category(
        json.loads((FIXTURES / "penny-percentage.json").read_text()),
        url="https://www.penny.de/angebote",
        valid_from=date(2026, 10, 5),
        valid_until=date(2026, 10, 10),
        observed_at=datetime.now(UTC),
    )
    assert items == []
