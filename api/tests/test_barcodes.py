import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from pricewatch_api.barcodes import source_ean, valid_ean
from pricewatch_api.sources import parse_aldi


@pytest.mark.parametrize("code", ["96385074", "4006381333931", "04006381333931"])
def test_supported_lengths_and_leading_zeros(code):
    assert valid_ean(code)
    assert source_ean({"gtin": code}) == code


@pytest.mark.parametrize(
    "code",
    [
        "4006381333932",
        "1234567890123",
        4006381333931,
        "000000000000523858",
        "４００６３８１３３３９３１",
    ],
)
def test_invalid_and_internal_identifiers_are_not_barcodes(code):
    assert not valid_ean(code)
    assert source_ean({"ean": code}) is None


def test_no_guessing_from_sku_nested_products_or_multiple_variants():
    code = "4006381333931"
    assert source_ean({"sku": code, "objectID": code, "klNr": code}) is None
    assert source_ean({"variants": [{"ean": code}]}) is None
    assert source_ean({"ean": [code, "96385074"]}) is None
    assert source_ean({"ean": code}, {"gtin": "96385074"}) is None
    assert source_ean({"ean": code, "gtin13": code}) == code


def test_aldi_import_preserves_only_explicit_barcodes():
    raw = json.loads(
        Path(__file__).with_name("fixtures").joinpath("aldi-next-data.json").read_text()
    )
    data = json.loads(raw["props"]["pageProps"]["apiData"])
    products = data[0][1]["res"]["algoliaDataMap"]
    # Synthetic parser case, not an asserted barcode for the fixture's real goods.
    products["1013"]["ean"] = "04006381333931"
    raw["props"]["pageProps"]["apiData"] = data
    items = parse_aldi(f'<script id="__NEXT_DATA__">{json.dumps(raw)}</script>', datetime.now(UTC))
    assert next(p for p in items if p.source_product_id == "1013").ean == "04006381333931"
    assert next(p for p in items if p.source_product_id != "1013").ean is None
