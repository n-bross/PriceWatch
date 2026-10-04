from datetime import date

import pytest

from pricewatch_api.retailer_sources import parse_rossmann_capture_price as capture_price_cents
from pricewatch_api.rossmann_recurring import START_URL, campaign_dates, parse_page


def test_public_rossmann_reduced_price_does_not_take_former_price():
    text = "8,69 €Ehemaliger Preis 8,69 € 8.49€Aktueller Artikelpreis:  8,49 €"
    assert capture_price_cents(text) == 849


def test_former_price_alone_is_not_a_purchase_price():
    assert capture_price_cents("8,69 €Ehemaliger Preis 8,69 €") is None


@pytest.fixture
def capture():
    return {
        "url": START_URL,
        "dateText": "Gültig ab Montag: 28.09. - 04.10.2026",
        "cards": [{
            "dateText": "Gültig ab Montag: 28.09. - 04.10.2026",
            "name": "  ISANA\n  Shampoo  ",
            "package_label": "250 ml (1 l = 3,96 €)",
            "priceText": "Aktueller Artikelpreis: 0,99 €",
            "source_url": "https://www.rossmann.de/de/pflege-shampoo/p/4305615000001",
        }],
        "next": None,
    }


@pytest.mark.parametrize("year", [2025, 2026, 2030])
def test_campaign_dates_uses_displayed_dates_and_year(year):
    assert campaign_dates(f"Gültig ab Montag: 28.09. - 04.10.{year}") == (
        date(year, 9, 28), date(year, 10, 4)
    )


@pytest.mark.parametrize("text", [None, "", "Angebote", "Gültig ab Montag: 28.09. - 04.10."])
def test_campaign_dates_requires_explicit_date_text(text):
    with pytest.raises(ValueError, match="Missing explicit ROSSMANN campaign dates"):
        campaign_dates(text)


@pytest.mark.parametrize("year", [2026, 2030])
def test_campaign_dates_resolves_start_and_end_year_rollover(year):
    assert campaign_dates(f"Gültig ab Montag: 29.12. - 04.01.{year}") == (
        date(year - 1, 12, 29), date(year, 1, 4)
    )


@pytest.mark.parametrize("end_day", [1, 15])
def test_campaign_dates_accepts_zero_and_fourteen_day_spans(end_day):
    assert campaign_dates(f"Gültig ab Montag: 01.06. - {end_day:02d}.06.2026") == (
        date(2026, 6, 1), date(2026, 6, end_day)
    )


@pytest.mark.parametrize("span", ["01.06. - 16.06.2026", "08.06. - 07.06.2026"])
def test_campaign_dates_rejects_long_or_reversed_span(span):
    with pytest.raises(ValueError, match="Unexpected ROSSMANN campaign duration"):
        campaign_dates(f"Gültig ab Montag: {span}")


def test_campaign_dates_rejects_impossible_calendar_date():
    with pytest.raises(ValueError):
        campaign_dates("Gültig ab Montag: 31.02. - 07.03.2026")


def test_parse_page_preserves_valid_card_and_campaign_evidence(capture):
    rows, next_url = parse_page(capture, "2026-10-01")
    assert next_url is None
    assert rows == [{
        "source": "rossmann_browser",
        "retailer": "ROSSMANN",
        "source_product_id": "4305615000001",
        "name": "ISANA Shampoo",
        "ean": None,
        "listed_offer": True,
        "price_cents": 99,
        "price_date": "2026-10-01",
        "scope": "online",
        "kind": "offer",
        "source_url": capture["cards"][0]["source_url"],
        "valid_from": "2026-09-28",
        "valid_until": "2026-10-04",
        "package_label": "250 ml (1 l = 3,96 €)",
        "conditions_text": "Öffentlich beobachteter Onlinepreis; Filialpreis und Verfügbarkeit "
                           "nicht bestätigt.",
    }]


@pytest.mark.parametrize("observed", ["2026-09-28", "2026-10-04"])
def test_parse_page_accepts_inclusive_campaign_bounds(capture, observed):
    rows, _ = parse_page(capture, observed)
    assert rows[0]["price_date"] == observed


@pytest.mark.parametrize("observed", ["2026-09-27", "2026-10-05"])
def test_parse_page_rejects_future_or_expired_campaign(capture, observed):
    with pytest.raises(ValueError, match="No verifiable public price cards"):
        parse_page(capture, observed)


@pytest.mark.parametrize("observed", ["2025-12-29", "2026-01-04"])
def test_parse_page_validates_campaign_across_new_year(capture, observed):
    capture["cards"][0]["dateText"] = "Gültig ab Montag: 29.12. - 04.01.2026"
    rows, _ = parse_page(capture, observed)
    assert rows[0]["valid_from"] == "2025-12-29"
    assert rows[0]["valid_until"] == "2026-01-04"


def test_parse_page_card_dates_do_not_require_banner(capture):
    del capture["dateText"]
    rows, _ = parse_page(capture, "2026-10-01")
    assert rows[0]["valid_from"] == "2026-09-28"


@pytest.mark.parametrize("text,cents", [
    ("Aktueller Artikelpreis:  8,49 €", 849),
    ("Artikelpreis 1,29 €", 129),
    ("Price 12,99 €", 1299),
    ("8,69 €Ehemaliger Preis 8,69 € 8.49€Aktueller Artikelpreis:  8,49 €", 849),
])
def test_parse_page_reads_explicit_purchase_price(capture, text, cents):
    capture["cards"][0]["priceText"] = text
    rows, _ = parse_page(capture, "2026-10-01")
    assert rows[0]["price_cents"] == cents


@pytest.mark.parametrize("text", [
    None, "", "8,69 €Ehemaliger Preis 8,69 €", "20 Punkte", "8,49 €",
    "Aktueller Artikelpreis: 8.49 €", "Aktueller Artikelpreis: 8,4 €",
    "Aktueller Artikelpreis: 0,00 €", "Aktueller Artikelpreis: -1,00 €",
])
def test_parse_page_rejects_cards_without_positive_purchase_price(capture, text):
    capture["cards"][0]["priceText"] = text
    with pytest.raises(ValueError, match="No verifiable public price cards"):
        parse_page(capture, "2026-10-01")


@pytest.mark.parametrize("url", [
    None, "", "/de/shampoo/p/123", "http://www.rossmann.de/de/shampoo/p/123",
    "https://example.com/de/shampoo/p/123",
    "https://www.rossmann.de.example.com/de/shampoo/p/123",
    "https://www.rossmann.de@evil.example/de/shampoo/p/123",
    "https://www.rossmann.de/de/shampoo/123", "https://www.rossmann.de/de/shampoo/p/",
])
def test_parse_page_rejects_empty_or_invalid_product_url(capture, url):
    capture["cards"][0]["source_url"] = url
    with pytest.raises(ValueError, match="No verifiable public price cards"):
        parse_page(capture, "2026-10-01")


@pytest.mark.parametrize("name", [None, "", " \n\t "])
def test_parse_page_rejects_empty_product_name(capture, name):
    capture["cards"][0]["name"] = name
    with pytest.raises(ValueError, match="No verifiable public price cards"):
        parse_page(capture, "2026-10-01")


@pytest.mark.parametrize("cards", [[], [{}]])
def test_parse_page_rejects_empty_or_unverifiable_cards(capture, cards):
    capture["cards"] = cards
    with pytest.raises(ValueError, match="No verifiable public price cards"):
        parse_page(capture, "2026-10-01")


def test_parse_page_skips_invalid_cards_and_keeps_distinct_products(capture):
    valid = capture["cards"][0]
    capture["cards"] += [
        {}, {**valid, "priceText": None}, {**valid, "source_url": ""},
        {**valid, "source_url": "https://www.rossmann.de/de/soap/p/4305615000002"},
    ]
    rows, _ = parse_page(capture, "2026-10-01")
    assert [row["source_product_id"] for row in rows] == ["4305615000001", "4305615000002"]


@pytest.mark.parametrize("suffix", ["", "?tracking=offer"])
def test_parse_page_does_not_emit_duplicate_product_ids(capture, suffix):
    card = capture["cards"][0]
    capture["cards"].append({**card, "source_url": card["source_url"] + suffix})
    rows, _ = parse_page(capture, "2026-10-01")
    assert len(rows) == 1
    assert rows[0]["source_product_id"] == "4305615000001"


@pytest.mark.parametrize("field", ["url", "next"])
@pytest.mark.parametrize("url", [
    "/de/angebote/m/angebote?page=2",
    "http://www.rossmann.de/de/angebote/m/angebote?page=2",
    "https://example.com/de/angebote/m/angebote?page=2",
    "https://www.rossmann.de.example.com/de/angebote/m/angebote?page=2",
    "https://www.rossmann.de/de/other?page=2",
    "https://www.rossmann.de/de/angebote/m/angebote/?page=2",
])
def test_parse_page_rejects_unsafe_listing_and_pagination_urls(capture, field, url):
    capture[field] = url
    message = "Unexpected ROSSMANN listing URL" if field == "url" else "Unsafe or non-advancing"
    with pytest.raises(ValueError, match=message):
        parse_page(capture, "2026-10-01")


@pytest.mark.parametrize("missing", [False, True])
def test_parse_page_requires_listing_url(capture, missing):
    if missing:
        del capture["url"]
    else:
        capture["url"] = ""
    with pytest.raises(ValueError, match="Unexpected ROSSMANN listing URL"):
        parse_page(capture, "2026-10-01")


def test_parse_page_rejects_non_advancing_pagination(capture):
    capture["next"] = capture["url"]
    with pytest.raises(ValueError, match="Unsafe or non-advancing"):
        parse_page(capture, "2026-10-01")


def test_parse_page_allows_same_listing_with_next_page_query(capture):
    capture["url"] = START_URL + "?page=2"
    capture["next"] = START_URL + "?page=3"
    rows, next_url = parse_page(capture, "2026-10-01")
    assert len(rows) == 1
    assert next_url == START_URL + "?page=3"


@pytest.mark.parametrize("next_url", [None, ""])
def test_parse_page_accepts_final_page_without_next_link(capture, next_url):
    capture["next"] = next_url
    rows, actual_next = parse_page(capture, "2026-10-01")
    assert len(rows) == 1
    assert actual_next == next_url


def test_listing_campaign_does_not_date_current_card_price(capture):
    del capture["cards"][0]["dateText"]
    rows, _ = parse_page(capture, "2026-10-01")
    assert rows[0]["kind"] == "unknown"
    assert rows[0]["listed_offer"] is False
    assert rows[0]["valid_from"] is None
    assert rows[0]["valid_until"] is None


def test_future_listing_does_not_hide_current_online_price(capture):
    del capture["cards"][0]["dateText"]
    rows, _ = parse_page(capture, "2026-09-27")
    assert rows[0]["price_date"] == "2026-09-27"
    assert rows[0]["valid_from"] is None


@pytest.mark.parametrize("banner", [
    None, "", "unrecognized", "Gültig ab Montag: 05.10. - 09.10.2026",
])
def test_advertised_card_does_not_inherit_banner_dates(capture, banner):
    capture["dateText"] = banner
    card = capture["cards"][0]
    card.pop("dateText")
    card["badges"] = ["Neu", "Aus der Werbung"]
    rows, _ = parse_page(capture, "2026-10-04")
    assert rows[0]["listed_offer"] is True
    assert rows[0]["valid_from"] is None
    assert rows[0]["valid_until"] is None


def test_mixed_cards_keep_individual_offer_evidence(capture):
    card = capture["cards"][0]
    card.pop("dateText")
    card["badges"] = ["Aus der Werbung"]
    capture["cards"].append({
        **card, "badges": ["Nur Online"],
        "source_url": "https://www.rossmann.de/de/soap/p/4305615000002",
    })
    rows, _ = parse_page(capture, "2026-10-04")
    assert [row["listed_offer"] for row in rows] == [True, False]
    assert all(row["valid_from"] is None for row in rows)


def test_run_without_banner_checkpoints_and_respects_cooldown(capture, tmp_path):
    from pricewatch_api.database import Database
    from pricewatch_api.observations import ObservationRepository
    from pricewatch_api.rossmann_recurring import run

    capture.pop("dateText")
    capture["cards"][0].pop("dateText")
    db = Database("sqlite:///:memory:")
    db.initialize()
    repository = ObservationRepository(db)
    state = tmp_path / "state.json"
    result = run(repository, state, lambda _: capture, now=100, observed_date="2026-10-04")
    assert result["status"] == "complete"
    assert result["rows"] == 1
    assert repository.query(source="rossmann_browser")["total"] == 1

    def unexpected_fetch(_):
        pytest.fail("Cooldown must not launch a browser")

    result = run(repository, state, unexpected_fetch, now=101, observed_date="2026-10-04")
    assert result["status"] == "cooldown"
    assert result["rows"] == 0


def test_capture_import_preserves_observation_day_and_ignores_listing_dates(capture):
    from pricewatch_api.rossmann_recurring import capture_rows

    capture['observed_at'] = '2026-10-01T23:30:00+00:00'
    capture['cards'][0].pop('dateText')
    capture['cards'][0]['listed_offer'] = True  # Legacy listing-wide assertion is not evidence.
    rows = capture_rows(capture)
    assert rows[0]['price_date'] == '2026-10-02'
    assert rows[0]['valid_from'] is None
    assert rows[0]['listed_offer'] is False


@pytest.mark.parametrize('timestamp', [None, '2026-10-02', '2026-10-02T10:00:00'])
def test_capture_import_rejects_unverified_observation_time(capture, timestamp):
    from pricewatch_api.rossmann_recurring import capture_rows

    capture['observed_at'] = timestamp
    with pytest.raises(ValueError, match='observation timestamp'):
        capture_rows(capture)


def test_run_resumes_after_success_and_does_not_advance_on_failure(capture, tmp_path):
    import json

    from pricewatch_api.rossmann_recurring import run

    saved = []

    class Repository:
        def save(self, rows):
            saved.extend(rows)

    state = tmp_path / 'state.json'
    capture['next'] = START_URL + '?pageIndex=1'
    result = run(Repository(), state, lambda _: capture, max_pages=1,
                 now=100, observed_date='2026-10-04')
    assert result['status'] == 'running'
    assert len(saved) == 1

    def failing_fetch(url):
        assert url == capture['next']
        raise ValueError('No public product cards: HTTP 403')

    result = run(Repository(), state, failing_fetch, now=101, observed_date='2026-10-04')
    checkpoint = json.loads(state.read_text())
    assert result['status'] == 'blocked'
    assert result['rows'] == 0
    assert checkpoint['next'] == capture['next']
    assert checkpoint['last_success'] == 100
    assert len(saved) == 1


def test_run_does_not_checkpoint_failed_database_write(capture, tmp_path):
    import json

    from pricewatch_api.rossmann_recurring import run

    class Repository:
        def save(self, rows):
            raise RuntimeError('database unavailable')

    state = tmp_path / 'state.json'
    result = run(Repository(), state, lambda _: capture, now=100,
                 observed_date='2026-10-04')
    assert result['status'] == 'blocked'
    assert result['rows'] == 0
    assert 'pages' not in json.loads(state.read_text())
