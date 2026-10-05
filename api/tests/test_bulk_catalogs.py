import json

import httpx
import pytest

from pricewatch_api.bulk_catalogs import (
    RateLimited,
    fetch,
    globus_categories,
    parse_combi,
    parse_globus,
)


def test_globus_price_and_ean_are_scoped_to_card():
    html = """<div class="product-box" data-product-information='{"id":"id1"}'>
    <a class="product-name" href="/item/">Apfel</a>
    <a data-product-gtin="4250241201186"></a>
    <span class="product-price-unit">1 kg (9,99 €/kg)</span>
    <div class="product-price-wrapper">Ab
    <span class="js-unit-price" data-value="1.99">1,99 €</span></div>
    </div><input name="p" value="999"><div class="pagination"><input name="p" value="3"></div>"""
    rows, pages = parse_globus(html, "https://produkte.globus.de/fruit/", "2026-10-03")
    assert pages == 3
    assert rows[0]["price_cents"] == 199
    assert rows[0]["ean"] == "4250241201186"
    assert rows[0]["scope"] == "unknown"
    assert rows[0]["price_qualifier"] == "from"
    rows, _ = parse_globus(
        html.replace("4250241201186", "4250241201187"), "https://produkte.globus.de/"
    )
    assert rows[0]["ean"] is None
    rows, _ = parse_globus(
        html.replace("js-unit-price", "old-price"), "https://produkte.globus.de/"
    )
    assert rows == []


def test_combi_explicit_offer_no_ean_from_url_or_sku():
    item = {
        "@type": "Product",
        "sku": "4250241201186",
        "name": "Produkt",
        "offers": {
            "priceSpecification": {"price": "1.15", "priceCurrency": "EUR"},
            "availability": "https://schema.org/InStock",
        },
    }

    def wrap():
        return '<script type="application/ld+json">' + json.dumps(item) + "</script>"

    rows = parse_combi(wrap(), "https://www.combi.de/product.html")
    assert rows[0]["ean"] is None
    assert rows[0]["price_cents"] == 115
    assert rows[0]["scope"] == "online"
    item["offers"]["availability"] = "https://schema.org/OutOfStock"
    assert parse_combi(wrap(), "https://www.combi.de/product.html") == []


def test_categories_restrict_host_and_non_product_links():
    html = '<a href="/frische-produkte/">A</a><a href="/frische-produkte/">B</a>'
    html += '<a href="/restaurant/">C</a><a href="https://other.de/food/">D</a>'
    assert globus_categories(html) == ["https://produkte.globus.de/frische-produkte/"]


def test_rate_limit_stops_without_retry():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(429, headers={"Retry-After": "120"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(RateLimited) as error:
            fetch(client, "https://www.combi.de/")
    assert error.value.retry_after == 120
    assert len(calls) == 1


def test_recurring_cycle_resumes_and_refreshes_only_when_due(tmp_path, monkeypatch):
    from pricewatch_api import bulk_catalogs as bulk
    from pricewatch_api.database import Database
    from pricewatch_api.observations import ObservationRepository

    url = f"sqlite:///{tmp_path / 'test.db'}"
    db = Database(url)
    db.initialize()
    monkeypatch.setenv("DATABASE_URL", url)
    clock = [100000.0]
    monkeypatch.setattr(bulk.time, "time", lambda: clock[0])
    monkeypatch.setattr(bulk.time, "sleep", lambda _: None)
    calls = []

    def fetch(client, url):
        calls.append(url)
        if url == bulk.GLOBUS:
            return '<a href="/fruit/">Fruit</a><a href="/veg/">Veg</a>', "2026-10-04"
        price = "1.99" if clock[0] == 100000 else "2.99"
        return (
            f'''<div class="product-box" data-product-information='{{"id":"{url}"}}'>
        <a class="product-name" href="/item/">Apple</a>
        <a data-product-gtin="4250241201186"></a><span class="product-price-unit"></span>
        <span class="product-manufacturer"></span>
        <span class="js-unit-price" data-value="{price}"></span></div>''',
            "2026-10-04",
        )

    monkeypatch.setattr(bulk, "fetch", fetch)
    kwargs = dict(source="globus", max_pages=1, workers=1, state_dir=tmp_path / "state")
    first = bulk.run(**kwargs)
    assert not first["complete"]
    assert len(first["completed"]) == 1
    second = bulk.run(**kwargs)
    assert second["complete"]
    assert len(second["products"]) == 2
    before = len(calls)
    bulk.run(**kwargs)
    assert len(calls) == before
    clock[0] += 86401
    bulk.run(**kwargs)
    assert len(calls) == before + 2
    prices = ObservationRepository(db).query(source="globus_website")["items"]
    assert {p["price_cents"] for p in prices} == {199, 299}


def test_failed_pages_cannot_prevent_future_cycles_forever(tmp_path, monkeypatch):
    from pricewatch_api import bulk_catalogs as bulk
    from pricewatch_api.database import Database
    from pricewatch_api.observations import ObservationRepository

    url = f"sqlite:///{tmp_path / 'test.db'}"
    db = Database(url)
    db.initialize()
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setattr(bulk.time, "sleep", lambda _: None)

    def fetch(client, url):
        if url == bulk.GLOBUS:
            return '<a href="/fruit/">Fruit</a>', "2026-10-04"
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(bulk, "fetch", fetch)
    for _ in range(3):
        state = bulk.run("globus", state_dir=tmp_path / "state")
    assert state["complete"]
    assert state["errors"]
    assert not state["products"]
    assert ObservationRepository(db).query(source="globus_website")["total"] == 0
