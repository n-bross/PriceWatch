"""Unit tests for deterministic retailer offer parsers and audits."""

import unittest

from pricewatch_api.barcodes import valid_ean
from pricewatch_api.database import Database
from pricewatch_api.observations import ObservationRepository
from pricewatch_api.retailer_sources import (
    audit_retailer_html,
    extract_dates,
    parse_norma_html,
)

NORMA_FIXTURE = """
<article class="b463 produktBoxContainer" id="of_387697">
  <a
 href="/de/angebote/ab-freitag,-02.10.26/wochenend-spezial-t-386978/selektion-schuemli-i-387697/"
 id="a_387697">
    <div
 class="produktBox produktBox--pre bfsg articleMarke_11124 produktBox-wochenend_spezial gelbpink">
      <div class="produktBox-img produktBox-img--center">
        <img
 alt="" src="/ext/img/product/angebote/26_10_02/100_selektion-schuemli_wo.png"/>
        <div class="produktBox-img-overlay"><ul><li class="inhalt"><p>1 kg</p></li></ul></div>
      </div>
      <div class="produktBox-txt">
        <hr/>
        <strong class="supplier">Käfer</strong>
        <h3 class="produktBox-txt-headline">Selektion Schümli</h3>
        <ul style="background-color: rgba(255,255,255,0.8)">
          <li class="produktBox-txt-inh">je 1 kg</li>
          <li class="produktBox-txt-price">1 kg = 12,99</li>
        </ul>
      </div>
      <div class="produktBox-cont">
        <div class="produktBox-cont-wrapper produktBox-cont-wrapper-gelbpink">
          <div
 class="produktBox-cont-wrapper-billiger" title="Sie sparen: 4,00 Euro">
<p>23% billiger</p>
</div>
          <ul>
            <li class="produktBox-cont-wrapper-uvp">UVP = 16,99</li>
            <li
 class="produktBox-cont-wrapper-price">
<span aria-label="12,99 Euro">12,99<sup>*</sup>
</span>
</li>
          </ul>
        </div>
      </div>
    </div>
  </a>
  <div
 class="productBox-available">
<ul>
<li>Filiale <i
 class="produktBoxIconFiliale" title="Erhältlich in Ihrer Filiale">
</i>
</li>
</ul>
</div>
</article>
<article class="b463 produktBoxContainer" id="of_387698">
  <a
 href="/de/angebote/ab-freitag,-02.10.26/wochenend-spezial-t-386978/all-in-1-spuelmaschinen-caps-tabs-i-387698/"
 id="a_387698">
    <div
 class="produktBox produktBox--pre bfsg articleMarke_78692 produktBox-wochenend_spezial gelbpink">
      <div class="produktBox-img produktBox-img--center">
        <img
 alt="Nur gültig vom 02.10. bis 04.10.2026 und nur mit der NORMA Pluss App 33% billiger: 10,99"
 src="/ext/img/product/angebote/26_10_02/100_all-in-1-spuelmaschinen-caps-tabs_wo.png"/>
        <div
 class="produktBox-img-overlay">
<ul>
<li
 class="inhalt">
<p>89/93 Caps</p>
</li>
<li>
<p>27% billiger</p>
</li>
</ul>
</div>
      </div>
      <div class="produktBox-txt">
        <hr/>
        <strong class="supplier">Finish</strong>
        <h3 class="produktBox-txt-headline">All in 1 Spülmaschinen Caps / Tabs</h3>
        <ul style="background-color: rgba(255,255,255,0.8)">
          <li class="produktBox-txt-inh">z.B. Power je 93 Taps</li>
          <li class="produktBox-txt-price">pro Waschgang –,13 ohne App</li>
          <li class="produktBox-txt-price">pro Waschgang –,12 mit App</li>
        </ul>
      </div>
      <div class="produktBox-cont">
        <div class="produktBox-cont-wrapper produktBox-cont-wrapper-gelbpink">
          <div class="produktBox-cont-wrapper-billiger-spacer"></div>
          <ul>
            <li class="produktBox-cont-wrapper-uvp-spacer"></li>
            <li
 class="produktBox-cont-wrapper-price">
<span aria-label="11,99 Euro">11,99<sup>*</sup>
</span>
</li>
          </ul>
        </div>
      </div>
    </div>
  </a>
  <div
 class="productBox-available">
<ul>
<li>Filiale <i
 class="produktBoxIconFiliale" title="Erhältlich in Ihrer Filiale">
</i>
</li>
</ul>
</div>
</article>
"""


class TestRetailerSources(unittest.TestCase):
    def test_norma_parser_exact_values(self):
        results = parse_norma_html(NORMA_FIXTURE, price_date="2026-10-02")
        self.assertEqual(len(results), 2)

        # First card: Käfer Selektion Schümli
        kaefer = results[0]
        self.assertEqual(kaefer["retailer"], "NORMA")
        self.assertEqual(kaefer["source"], "retailer_website_v2")
        self.assertEqual(kaefer["source_product_id"], "387697")
        self.assertEqual(kaefer["name"], "Käfer Selektion Schümli")
        self.assertEqual(kaefer["brand"], "Käfer")
        self.assertEqual(kaefer["package_label"], "je 1 kg")
        self.assertEqual(kaefer["price_cents"], 1299)
        self.assertEqual(kaefer["valid_from"], "2026-10-02")
        self.assertIsNone(kaefer["valid_until"])  # Never invent expiry!
        self.assertIsNone(kaefer["ean"])  # Never guessed EAN!
        self.assertEqual(kaefer["scope"], "unknown")
        self.assertEqual(kaefer["kind"], "offer")
        self.assertTrue(kaefer["source_url"].endswith("#of_387697"))

        # Second card: Finish All in 1 Caps
        finish = results[1]
        self.assertEqual(finish["retailer"], "NORMA")
        self.assertEqual(finish["source_product_id"], "387698")
        self.assertEqual(finish["name"], "Finish All in 1 Spülmaschinen Caps / Tabs")
        self.assertEqual(finish["brand"], "Finish")
        self.assertEqual(finish["package_label"], "z.B. Power je 93 Taps")
        self.assertEqual(finish["price_cents"], 1199)
        self.assertEqual(finish["valid_from"], "2026-10-02")
        self.assertIsNone(finish["valid_until"])
        self.assertIsNone(finish["ean"])

    def test_wrong_price_exclusion(self):
        """UVP, unit prices, discounts, and app prices must not become price_cents."""
        results = parse_norma_html(NORMA_FIXTURE)
        kaefer = results[0]
        finish = results[1]

        # UVP was 16.99, billiger was 4.00 savings -> price must be 12.99
        self.assertNotEqual(kaefer["price_cents"], 1699)
        self.assertNotEqual(kaefer["price_cents"], 400)
        self.assertEqual(kaefer["price_cents"], 1299)

        # Unit price was 0.13, app promotion was 10.99 -> price must be shelf 11.99
        self.assertNotEqual(finish["price_cents"], 13)
        self.assertNotEqual(finish["price_cents"], 12)
        self.assertNotEqual(finish["price_cents"], 1099)
        self.assertEqual(finish["price_cents"], 1199)

    def test_date_handling_conservative(self):
        # 1. 'ab' start only -> valid_until must be None
        valid_from, valid_until = extract_dates("", "/de/angebote/ab-freitag,-02.10.26/")
        self.assertEqual(valid_from, "2026-10-02")
        self.assertIsNone(valid_until)

        # 2. Undated url and text -> both None
        valid_from, valid_until = extract_dates("Ganzjährig im Sortiment", "/de/sortiment/")
        self.assertIsNone(valid_from)
        self.assertIsNone(valid_until)

        # 3. Explicit range -> both parsed
        valid_from, valid_until = extract_dates("Aktion vom 02.10. bis 04.10.2026 im Markt")
        self.assertEqual(valid_from, "2026-10-02")
        self.assertEqual(valid_until, "2026-10-04")

    def test_ean_honesty(self):
        card_no_ean = (
            '<article class="produktBoxContainer" id="of_1">'
            '<div class="produktBox-txt">'
            '<h3 class="produktBox-txt-headline">Wasser</h3></div>'
            '<li class="produktBox-cont-wrapper-price">'
            '<span aria-label="0,49 Euro">0,49</span></li></article>'
        )
        res = parse_norma_html(card_no_ean)
        self.assertIsNone(res[0]["ean"])

        card_invalid_ean = (
            '<article class="produktBoxContainer" id="of_2" data-ean="123456">'
            '<div class="produktBox-txt">'
            '<h3 class="produktBox-txt-headline">Wasser</h3></div>'
            '<li class="produktBox-cont-wrapper-price">'
            '<span aria-label="0,49 Euro">0,49</span></li></article>'
        )
        res = parse_norma_html(card_invalid_ean)
        self.assertIsNone(res[0]["ean"])

        # Valid GTIN-13: 4000417025005 (Haribo Goldbären)
        self.assertTrue(valid_ean("4000417025005"))
        card_valid_ean = (
            '<article class="produktBoxContainer" id="of_3" '
            'data-ean="4000417025005">'
            '<div class="produktBox-txt">'
            '<h3 class="produktBox-txt-headline">Haribo</h3></div>'
            '<li class="produktBox-cont-wrapper-price">'
            '<span aria-label="1,19 Euro">1,19</span></li></article>'
        )
        res = parse_norma_html(card_valid_ean)
        self.assertEqual(res[0]["ean"], "4000417025005")

    def test_audit_non_structured_retailers(self):
        netto_dog_html = (
            "<p>Willkommen auf unserer Prospektseite! Hier findest du "
            "alle aktuellen Angebote im Blätterprospekt.</p>"
        )
        audit = audit_retailer_html("netto_dog", netto_dog_html)
        self.assertFalse(audit["supports_structured_offers"])
        self.assertEqual(audit["source_type"], "leaflet_viewer_only")

        markant_html = "<div>Markt auswählen Rezepte Menü</div>"
        audit = audit_retailer_html("markant", markant_html)
        self.assertFalse(audit["supports_structured_offers"])
        self.assertEqual(audit["source_type"], "requires_store_selection")

        wasgau_html = '<iframe src="https://wasgau-dlog.1kcloud.com/ep1rP1V0/"></iframe>'
        audit = audit_retailer_html("wasgau", wasgau_html)
        self.assertFalse(audit["supports_structured_offers"])
        self.assertEqual(audit["source_type"], "leaflet_viewer_only")

    def test_observation_repo_integration(self):
        db = Database("sqlite:///:memory:")
        db.initialize()
        repo = ObservationRepository(db)
        results = parse_norma_html(NORMA_FIXTURE, price_date="2026-10-02")
        saved = repo.save(results)
        self.assertEqual(saved, 2)

        queried = repo.query(retailer="NORMA")
        self.assertEqual(queried["total"], 2)
        item = queried["items"][0]
        self.assertEqual(item["source"], "retailer_website_v2")
        self.assertIn(item["price_cents"], (1199, 1299))


if __name__ == "__main__":
    unittest.main()
