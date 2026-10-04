# PriceWatch Continuation Status & Integration Reality Audit

**Status Stand:** 2026-10-04 16:20 CEST (Europe/Berlin)  
**Parent Thread:** `383b6f67-0b5f-419e-9ff1-44530b8f0362`  
**Workspace:** `/opt/t3code/worktrees/PriceWatch/t3code-e70d379d` (Branch: `t3code/supermarket-price-offers-api`)

---

## 1. Status Matrix: Implemented vs. Live-Verified vs. Deployed vs. Blocked

| Source / Retailer | Parser & Unit Tests | Live Verification (Real Fetch) | Systemd Service & Timer Deployed | Status & Operational Details |
| :--- | :--- | :--- | :--- | :--- |
| **Combi** | ✅ 6 tests passing | ✅ Live batches running continuously | ✅ `pricewatch-bulk-combi-e70d379d.timer` active (15m interval) | **DEPLOYED & LIVE RUNNING** (7.000+ items catalogued) |
| **Globus** | ✅ Tests passing | ✅ Live batches running | ✅ `pricewatch-bulk-globus-e70d379d.timer` active (15m interval) | **DEPLOYED & LIVE RUNNING** (61.682 observations) |
| **myTime** | ✅ Tests passing | ✅ Live batches running | ✅ `pricewatch-mytime-e70d379d.timer` active (15m interval) | **DEPLOYED & LIVE RUNNING** (24.821 observations) |
| **Denns / BIO COMPANY / Alnatura / Netto** | ✅ Tests passing | ✅ Live feeds active | ✅ `pricewatch-recovered-offers-e70d379d.timer` active (6h interval) | **DEPLOYED & LIVE RUNNING** (Ran successfully at 06:20 & 12:20 CEST) |
| **ROSSMANN Online Offers** | ✅ 72 tests passing (`test_rossmann_browser.py`) | ✅ **LIVE VERIFIED**: Headless browser crawled pages 0–20, successfully ingested **339 live items** with campaign dates `05.10. - 09.10.2026`. | ✅ `pricewatch-rossmann-e70d379d.service` & `.timer` installed & enabled on host systemd. | **DEPLOYED & LIVE VERIFIED** (In 6h backoff cooldown after hitting card layout boundary on p.21; next run at 19:55 CEST). |
| **EDEKA Public Offers** | ✅ 40 tests passing (`test_edeka_offers.py`) | ⚠️ **LIVE BLOCKED**: Akamai Edge Block (`errors.edgesuite.net` 403 Forbidden) intercepts server datacenter IP. | ✅ `pricewatch-edeka-e70d379d.service` & `.timer` installed & active on host systemd (00,06,12,18:30 CEST). | **DEPLOYED / LIVE BLOCKED (Akamai WAF)**: Service executes with flock and safe exponential cooldown backoff. |
| **REWE Automated Retrieval** | ✅ 2 tests passing (`test_rewe_browser.py`) | ✅ **AUTOMATED ENDPOINT VERIFIED**: Discovered official open REST endpoint `https://www.rewe.de/shop/api/products?serviceTypes=PICKUP&marketId=461766&attribute=discounted`. Returns **595 discounted products** with exact GTIN, `currentRetailPrice`, `regularPrice`, and explicit `validTo: 2026-10-10`. | ⏳ Systemd recurring service to be templated and wired to new REST endpoint. | **INVESTIGATION COMPLETE / AUTOMATED SOURCE CONFIRMED** (Overcomes Cloudflare HTML challenge without bypass). |

---

## 2. Retailer Verification Details & Evidence

### ROSSMANN Live Capture
- **Deployment:** Installed via `deploy/install-recurring.sh`. Service unit `/etc/systemd/system/pricewatch-rossmann-e70d379d.service` executes `scripts/sync_rossmann.py --max-pages 5`.
- **Live Output:** 
  - Crawled through pages 0 to 20 under campaign `"Gültig ab Montag: 05.10. - 09.10.2026"`.
  - Ingested 339 fresh price observations into `external_price_observations` with exact source URLs, package labels, prices in cents, and online scope disclaimer.
  - Page 21 stopped at challenge/boundary, cleanly entering 6h cooldown until `2026-10-04 19:55:18 CEST`.

### EDEKA Public Advertised Offers
- **Deployment:** Installed via `deploy/install-recurring.sh`. Unit `/etc/systemd/system/pricewatch-edeka-e70d379d.service` and `.timer` run on calendar `00,06,12,18:30:00 Europe/Berlin`.
- **Blocker Investigation:** 
  - Direct HTTP and headless Chrome to `https://www.edeka.de/angebote/` return `403 Forbidden` (`server: AkamaiGHost`, `errors.edgesuite.net`).
  - Unit properly records status `"failed": "HTTPStatusError 403"` and enters cooldown backoff without crashing system state.

### REWE Automated Public Retrieval
- **Investigation Outcome:**
  - Public HTML market page (`rewe.de/marktseite/...`) is behind Cloudflare Turnstile challenge.
  - However, REWE's official shop API (`https://www.rewe.de/shop/api/products`) is fully open over standard HTTP and honors store, channel, and postal parameters:
    - Query: `serviceTypes=PICKUP&marketId=461766&attribute=discounted`
    - Returns 595 current promotions for Grafing (Markt 461766, Leonhardstr. 5a).
    - Every product payload includes:
      - `gtin`: unambiguous EAN barcode (e.g. `28003199`, `4015000969598`).
      - `pricing.currentRetailPrice`: offer price in cents.
      - `pricing.discount.regularPrice`: normal price in cents.
      - `pricing.discount.validTo`: explicit campaign validity (e.g. `2026-10-10T00:00:00CEST`).
      - `pricing.grammage` & `basePrice`: unit price.

---

## 3. Active Systemd Timers on Host (`sudo systemctl list-timers 'pricewatch-*'`)

11 active timers verified on host systemd:
1. `pricewatch-sync-e70d379d.timer` (15m interval)
2. `pricewatch-bulk-globus-e70d379d.timer` (15m interval)
3. `pricewatch-bulk-combi-e70d379d.timer` (15m interval)
4. `pricewatch-mytime-e70d379d.timer` (15m interval)
5. `pricewatch-rossmann-e70d379d.timer` (15m interval / guarded by next_due)
6. `pricewatch-dm-e70d379d.timer` (30m interval)
7. `pricewatch-recovered-offers-e70d379d.timer` (6h interval at 00,06,12,18:20)
8. `pricewatch-edeka-e70d379d.timer` (6h interval at 00,06,12,18:30)
9. `pricewatch-external-e70d379d.timer` (daily 05:00)
10. `pricewatch-retailer-pages-e70d379d.timer` (daily 06:40)
11. `pricewatch-catalog-e70d379d.timer` (weekly Sunday 04:00)

---

## 4. T3 Persistent Monitor Schedule

- **Task ID:** `scheduled-task:9e8239c7-5d50-452c-b767-925425f16344`
- **Schedule:** `everyMs: 18300000` (5 hours, 5 minutes)
- **Status:** **Active (`enabled: true`)**, bound to this thread.
