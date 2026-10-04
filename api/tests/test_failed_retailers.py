import json

from pricewatch_api.failed_retailers import (
    parse_alnatura,
    parse_bio_company,
    parse_denns,
    parse_netto_dog,
)

TODAY = "2026-10-03"


def test_bio_actual_price_not_strike_or_unit_price():
    html = """Gültig von 01.10.2026 bis 14.10.2026
    <div class="dealscard"><span class="dealscardHeadline">Kernbrot</span>
    <span class="dealscardOverline">WIENER BROT</span><div class="info">
    <strong>500 g</strong>1 kg=7,38</div><span class="strike">4,69</span>
    <div class="dealsprice"><span class="euro">3,</span><span class="cent">69</span>
    </div></div>"""
    (row,) = parse_bio_company(html, "https://www.biocompany.de/", TODAY, "Berlin")
    assert row["price_cents"] == 369
    assert row["ean"] is None and row["valid_until"] == "2026-10-14"
    assert "Berlin" in row["conditions_text"]


def test_denns_variants_dates_and_hidden_products():
    base = dict(
        _id="a",
        title="Kürbis",
        land="de",
        price="1,99",
        priceb="3,49",
        pricec="1 kg=3,00",
        validfrom="2026-09-23",
        validto="2026-10-06",
        priceApp="1,49",
        appValidfrom="2026-10-01",
        appValidto="2026-10-06",
    )
    rows = parse_denns(
        {
            "nodes": [
                base,
                base,
                {**base, "_id": "b", "hidden": True},
                {**base, "_id": "c", "land": "at"},
                {**base, "_id": "d", "bmvOnly": True},
            ]
        },
        "https://biomarkt.de",
        TODAY,
    )
    assert {(r["price_cents"], r["requires_membership"]) for r in rows} == {
        (199, False),
        (149, True),
    }
    assert len(rows) == 2 and len({r["source_product_id"] for r in rows}) == 1


def test_netto_membership_and_mixed_variants_are_not_global_ean():
    offer = dict(
        id="coupon",
        title="Kaffee verschiedene Sorten",
        price=5.99,
        originalPrice=9.99,
        currency="EUR",
        type="mixedbuy",
        sales_EAN="4000508059087",
        membershipOffer=True,
        startTime="2026-09-28T02:00:00",
        endTime="2026-10-05T01:59:59",
        maximumQuantity=5,
    )
    payload = "1:" + json.dumps({"offers": [offer]}) + "\n"
    html = "<script>self.__next_f.push(" + json.dumps([1, payload]) + ")</script>"
    (row,) = parse_netto_dog(html, "https://netto.de/prospekte/", TODAY)
    assert row["requires_membership"] and row["ean"] is None
    assert row["price_cents"] == 599 and row["valid_until"] == "2026-10-04"
    assert "Höchstens 5" in row["conditions_text"]


def test_netto_dom_position_does_not_identify_product():
    template = """Angebote vom: 28-09-2026 bis 03-10-2026
    <div aria-label="product-0"><h4>{}</h4><p>500 g</p><h3>1.<span>99</span></h3></div>"""
    (a,) = parse_netto_dog(template.format("Kaffee"), "https://netto.de/a", TODAY)
    (b,) = parse_netto_dog(template.format("Butter"), "https://netto.de/b", TODAY)
    assert a["source_product_id"] != b["source_product_id"]


def test_alnatura_page_heading_dauerpreis_does_not_override_offer_dates():
    html = """<h1>DAUERPREIS</h1><section>
    <h2>Wochenangebote Obst &amp; Gemüse vom 28.09.2026 - 03.10.2026</h2>
    <article><div id="flag-slot-p">Wochenangebot</div>
    <div id="product-title-p">Kartoffeln</div><div id="weight-slot-p">1,5 kg</div>
    <div id="price-slot-p">2,99 € inkl. MwSt.</div></article>
    <article><div id="product-title-x">Käse</div>
    <div id="price-slot-x">Wählen Sie Ihren Alnatura Markt</div></article></section>"""
    (row,) = parse_alnatura(html, "https://www.alnatura.de/angebote", TODAY)
    assert row["price_cents"] == 299 and row["kind"] == "offer"
    assert row["valid_until"] == "2026-10-03"
