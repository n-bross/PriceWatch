"""Offline tests for explicit, dated EDEKA offers and their observation evidence."""

from datetime import UTC, date, datetime, timedelta

import pytest

from pricewatch_api.edeka_offers import parse_capture, parse_html

OBSERVED_AT = datetime(2026, 10, 1, 12, tzinfo=UTC)
PERIOD = "Gültig vom 28.09.2026 bis zum 04.10.2026"
DIALOG = """
<dialog id="dialog-angebot-milch">
  <h3>Angebot: <strong>Frische Milch</strong></h3>
  <p class="line-clamp-2">1 l <b>Packung</b></p>
  <div class="autoformat">Nur solange der Vorrat reicht.</div>
  <span class="sr-only">Rabattierter Preis von 1,29€</span>
  <span class="sr-only">App Preis von 0.99€ (mit EDEKA App)</span>
  <span class="sr-only">Bisheriger Preis von 1,49€</span>
  <span class="sr-only">10 PAYBACK Punkte</span>
</dialog>
"""


@pytest.fixture
def capture():
    return {
        "valid_from": "2026-09-28",
        "valid_until": "2026-10-04",
        "products": [
            {
                "id": "dialog-angebot-milch",
                "name": "Frische Milch",
                "description": "1 l Packung",
                "terms": "Nur solange der Vorrat reicht.",
                "prices": ["Rabattierter Preis von 1,29€", "App Preis von 0.99€"],
            }
        ],
    }


def test_capture_keeps_cash_and_app_offers_separate_with_source_evidence(capture):
    prices, records = parse_capture(capture, OBSERVED_AT)
    assert len(prices) == len(records) == 2
    cash, app = prices
    assert cash.source_product_id == "dialog-angebot-milch"
    assert app.source_product_id == "dialog-angebot-milch:app"
    assert cash.price_cents == 129
    assert app.price_cents == 99
    assert cash.requires_membership is False
    assert app.requires_membership is True
    assert cash.conditions == ("Nur in mit dieser Werbung gekennzeichneten, teilnehmenden Märkten")
    assert app.conditions == (
        cash.conditions
        + "; EDEKA App, Registrierung und Lieblingsmarkt erforderlich; nicht Hessenring"
    )
    for item, record in zip(prices, records, strict=True):
        assert item.retailer == "edeka"
        assert item.name == "Frische Milch"
        assert item.kind == "offer"
        assert item.scope == "chain_advertised"
        assert item.store_id is None
        assert item.postal_code is None
        assert item.ean is None
        assert item.package_label == "1 l Packung"
        assert item.valid_from == date(2026, 9, 28)
        assert item.valid_until == date(2026, 10, 4)
        assert item.observed_at == OBSERVED_AT
        assert str(item.source_url) == "https://www.edeka.de/angebote/#angebot-milch"
        assert record["source_product_id"] == item.source_product_id
        assert record["price_cents"] == item.price_cents
        assert record["requires_membership"] == item.requires_membership
        assert record["source"] == "edeka_public_offers"
        assert record["retailer"] == "EDEKA"
        assert record["valid_from"] == "2026-09-28"
        assert record["valid_until"] == "2026-10-04"
        assert record["price_date"] == "2026-10-01"
        assert record["conditions_text"] == "Nur solange der Vorrat reicht."
        assert record["region_label"] == ("Teilnehmende Märkte; keine bestätigte lokale Filiale")
        assert "observed_at" not in record


def test_observation_evidence_is_stable_within_a_day(capture):
    _, first = parse_capture(capture, OBSERVED_AT)
    later_prices, later = parse_capture(capture, OBSERVED_AT + timedelta(hours=1))
    assert first == later
    assert later_prices[0].observed_at == OBSERVED_AT + timedelta(hours=1)
    _, next_day = parse_capture(capture, OBSERVED_AT + timedelta(days=1))
    assert next_day[0]["price_date"] == "2026-10-02"


def test_capture_requires_timezone(capture):
    with pytest.raises(ValueError, match="timestamp needs a timezone"):
        parse_capture(capture, OBSERVED_AT.replace(tzinfo=None))


def test_browser_capture_period_provenance(capture):
    capture.update(source_url="https://www.edeka.de/angebote/", period_text=PERIOD)
    assert len(parse_capture(capture, OBSERVED_AT)[0]) == 2
    capture["valid_from"] = "2026-09-29"
    with pytest.raises(ValueError, match="dates disagree with source period"):
        parse_capture(capture, OBSERVED_AT)


def test_browser_capture_wrong_source(capture):
    capture["source_url"] = "https://example.org/angebote/"
    with pytest.raises(ValueError, match="official EDEKA offers source URL"):
        parse_capture(capture, OBSERVED_AT)


@pytest.mark.parametrize("label", ["Festpreis", "Rabattierter Preis", "App Preis"])
@pytest.mark.parametrize("amount", ["1,29", "1.29"])
def test_explicit_cash_price_labels_and_decimal_separators(capture, label, amount):
    capture["products"][0]["prices"] = [f"{label} von {amount}€ (je Packung)"]
    prices, _ = parse_capture(capture, OBSERVED_AT)
    assert len(prices) == 1
    assert prices[0].price_cents == 129
    assert prices[0].requires_membership == (label == "App Preis")


def test_historical_points_and_unrecognized_labels_do_not_become_prices(capture):
    capture["products"][0]["prices"] += [
        "Bisheriger Preis von 1,99€",
        "20 PAYBACK Punkte",
        "1,29€",
        "Festpreis von 1,2€",
    ]
    prices, _ = parse_capture(capture, OBSERVED_AT)
    assert [item.price_cents for item in prices] == [129, 99]


@pytest.mark.parametrize("products", [[], [{"id": "points", "prices": ["20 PAYBACK Punkte"]}]])
def test_capture_requires_at_least_one_explicit_purchase_price(capture, products):
    capture["products"] = products
    with pytest.raises(ValueError, match="No explicit EDEKA purchase prices"):
        parse_capture(capture, OBSERVED_AT)


@pytest.mark.parametrize("days", [0, 14])
def test_validity_period_accepts_boundary_lengths(capture, days):
    capture["valid_until"] = (date(2026, 9, 28) + timedelta(days=days)).isoformat()
    prices, _ = parse_capture(capture, OBSERVED_AT)
    assert prices[0].valid_until == date(2026, 9, 28) + timedelta(days=days)


@pytest.mark.parametrize("days", [-1, 15])
@pytest.mark.parametrize("parser", ["capture", "html"])
def test_invalid_validity_period_lengths_are_rejected(capture, days, parser):
    end = date(2026, 9, 28) + timedelta(days=days)
    with pytest.raises(ValueError, match="Unexpected EDEKA weekly validity period"):
        if parser == "capture":
            capture["valid_until"] = end.isoformat()
            parse_capture(capture, OBSERVED_AT)
        else:
            parse_html(f"Gültig vom 28.09.2026 bis zum {end:%d.%m.%Y}" + DIALOG, OBSERVED_AT)


@pytest.mark.parametrize("offer_start", ["ab 28.09.", "ab 01.10.", "ab 04.10."])
def test_card_specific_start_is_within_the_advertised_period(capture, offer_start):
    capture["products"][0]["start"] = offer_start
    prices, records = parse_capture(capture, OBSERVED_AT)
    expected = datetime.strptime(offer_start + "2026", "ab %d.%m.%Y").date()
    assert all(item.valid_from == expected for item in prices)
    assert all(record["valid_from"] == expected.isoformat() for record in records)


@pytest.mark.parametrize("offer_start", ["ab 29.12.", "ab 01.01."])
def test_card_start_resolves_year_across_new_year(capture, offer_start):
    capture.update(valid_from="2025-12-29", valid_until="2026-01-04")
    capture["products"][0]["start"] = offer_start
    prices, _ = parse_capture(capture, OBSERVED_AT)
    expected = date(2025, 12, 29) if offer_start == "ab 29.12." else date(2026, 1, 1)
    assert prices[0].valid_from == expected


@pytest.mark.parametrize("offer_start", ["01.10.", "ab 1.10.", "ab 01.10.2026"])
def test_unrecognized_card_start_is_rejected(capture, offer_start):
    capture["products"][0]["start"] = offer_start
    with pytest.raises(ValueError, match="Unrecognized EDEKA offer start"):
        parse_capture(capture, OBSERVED_AT)


@pytest.mark.parametrize("offer_start", ["ab 27.09.", "ab 05.10."])
def test_card_start_outside_period_is_rejected(capture, offer_start):
    capture["products"][0]["start"] = offer_start
    with pytest.raises(ValueError, match="EDEKA offer start outside advertised period"):
        parse_capture(capture, OBSERVED_AT)


@pytest.mark.parametrize("duplicate", ["Festpreis von 1,19€", "App Preis von 0,89€"])
@pytest.mark.parametrize("another_card", [False, True])
def test_duplicate_price_identity_is_rejected(capture, duplicate, another_card):
    if another_card:
        capture["products"].append({**capture["products"][0], "prices": [duplicate]})
    else:
        capture["products"][0]["prices"].append(duplicate)
    with pytest.raises(ValueError, match="Duplicate or ambiguous EDEKA offer price"):
        parse_capture(capture, OBSERVED_AT)


@pytest.mark.parametrize("description_class", ["line-clamp-2", "line-clmap-2"])
def test_html_extracts_dialog_text_and_matches_capture(capture, description_class):
    html = DIALOG.replace("line-clamp-2", description_class)
    actual = parse_html(f"<p>{PERIOD}</p><footer>{PERIOD}</footer>{html}", OBSERVED_AT)
    assert actual == parse_capture(capture, OBSERVED_AT)


def test_html_optional_description_and_terms(capture):
    html = """<dialog id="dialog-angebot-milch">
      <h3>Frische Milch</h3><span class="sr-only">Festpreis von 1,29€</span>
    </dialog>"""
    prices, records = parse_html(PERIOD + html, OBSERVED_AT)
    assert prices[0].name == "Frische Milch"
    assert prices[0].package_label is None
    assert records[0]["conditions_text"] == ""


@pytest.mark.parametrize("period", ["", PERIOD + " Gültig vom 05.10.2026 bis zum 11.10.2026"])
def test_html_needs_one_unambiguous_period(period):
    with pytest.raises(ValueError, match="one explicit, unambiguous validity period"):
        parse_html(period + DIALOG, OBSERVED_AT)


def test_html_rejects_missing_heading():
    html = DIALOG.replace("<h3>Angebot: <strong>Frische Milch</strong></h3>", "")
    with pytest.raises(ValueError, match="EDEKA offer dialog missing heading"):
        parse_html(PERIOD + html, OBSERVED_AT)


@pytest.mark.parametrize("body", ["Access Denied", DIALOG.replace("dialog-angebot-", "other-")])
def test_html_rejects_challenge_or_unrecognized_dialog_markup(body):
    with pytest.raises(ValueError, match="No EDEKA offer dialogs"):
        parse_html(PERIOD + body, OBSERVED_AT)


def test_html_card_start_can_repeat_but_cannot_conflict():
    html = DIALOG.replace("</dialog>", "<p>ab 01.10.</p><p>ab 01.10.</p></dialog>")
    prices, _ = parse_html(PERIOD + html, OBSERVED_AT)
    assert all(item.valid_from == date(2026, 10, 1) for item in prices)
    html = html.replace("</dialog>", "<p>ab 02.10.</p></dialog>")
    with pytest.raises(ValueError, match="Ambiguous EDEKA offer start"):
        parse_html(PERIOD + html, OBSERVED_AT)


def test_capture_price_date_uses_german_local_day(capture):
    # The UTC capture is already after midnight at the German retailer.
    _, records = parse_capture(capture, datetime(2026, 10, 1, 22, 30, tzinfo=UTC))
    assert records[0]["price_date"] == "2026-10-02"
