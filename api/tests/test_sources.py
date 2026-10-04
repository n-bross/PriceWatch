import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from pricewatch_api.sources import SourceError, cents, fetch_aldi, parse_aldi


def fixture_html():
    data = Path(__file__).with_name("fixtures").joinpath("aldi-next-data.json").read_text()
    return f'<script id="__NEXT_DATA__" type="application/json">{data}</script>'


def test_real_aldi_fixture_parses_prices_dates_unit_and_deposit():
    items = parse_aldi(fixture_html(), datetime.now(UTC))
    assert len(items) == 2
    red_bull = next(p for p in items if p.source_product_id == "1000083")
    assert red_bull.price_cents == 89
    assert red_bull.deposit_cents == 25
    assert str(red_bull.valid_from) == "2026-09-28"
    assert str(red_bull.valid_until) == "2026-10-03"
    assert red_bull.unit_price_cents == 356
    assert red_bull.unit_price_unit == "l"
    assert red_bull.scope == "chain_advertised"
    assert red_bull.regular_price_cents is None  # UVP is not a regular retailer price.
    assert "UVP" in red_bull.conditions


def test_recalled_and_unavailable_products_are_excluded():
    raw = json.loads(
        Path(__file__).with_name("fixtures").joinpath("aldi-next-data.json").read_text()
    )
    data = json.loads(raw["props"]["pageProps"]["apiData"])
    data[0][1]["res"]["algoliaDataMap"]["1013"]["isRecall"] = True
    raw["props"]["pageProps"]["apiData"] = data
    html = f'<script id="__NEXT_DATA__">{json.dumps(raw)}</script>'
    assert len(parse_aldi(html, datetime.now(UTC))) == 1


@pytest.mark.parametrize(
    "html",
    [
        "<html>blocked</html>",
        '<script id="__NEXT_DATA__">{}</script>',
        '<script id="__NEXT_DATA__">invalid json</script>',
    ],
)
def test_changed_source_format_fails_explicitly(html):
    with pytest.raises(SourceError):
        parse_aldi(html, datetime.now(UTC))


def test_source_http_errors_are_reported(monkeypatch):
    def forbidden(self, url):
        return httpx.Response(403, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", forbidden)
    with pytest.raises(SourceError, match="HTTP 403"):
        fetch_aldi()


def test_cents_uses_decimal_and_rejects_fractional_or_negative():
    assert cents(1.99) == 199
    for value in ["0.001", "-1", "NaN", "Infinity"]:
        with pytest.raises(ValueError):
            cents(value)
