# PriceWatch Preis-API

Backend für deutsche Supermarktpreise und Angebote. FastAPI mit OpenAPI/Swagger,
SQLite für lokale Entwicklung und PostgreSQL für Supabase/Deployment.

## Vergleichswebsite

[Website öffnen](https://vps.tail179a46.ts.net:9450/). Suche nach Produktname oder EAN,
PLZ- und Händlerfilter, Quellenlinks sowie getrennte App-/Archivpreise.
`GET /v1/compare` liefert die Vergleichsdaten, `GET /v1/coverage` die 34 Händlerprüfungen.
[Ergebnisse mit Abrufversuchen und Gründen je Händler](../docs/retailer-coverage.md).
Der Produktkatalog enthält auch Produkte, für die noch kein Preis vorliegt.

GLOBUS, Combi, HIT und NORMA werden täglich gegen frische öffentliche Seiten aktualisiert.
Der Timer `pricewatch-retailer-pages-e70d379d.timer` läuft ab etwa 06:40 Uhr Berliner Zeit.
Die Vorlagen liegen unter `deploy/pricewatch-retailer-pages.*`; `@API_DIR@` muss ersetzt werden.
Bei fehlgeschlagenem Live-Abruf werden alte HTML-Dateien nicht mit einem neuen Preisdatum versehen.
REWE, EDEKA und ROSSMANN verwenden bislang geprüfte Browserimporte; kein unbeaufsichtigter
Browserabruf bei geschlossener T3-Verbindung. Vollständige Preislisten aller Händler liegen nicht vor.

## Laufende Aktualisierung der erweiterten Importe

GLOBUS-, Combi- und myTime-Sortimente erhalten wiederkehrende, begrenzte
Importläufe; Denns, BIO COMPANY, Alnatura und Netto mit Hund werden alle sechs
Stunden geprüft. Fortschritt bleibt zwischen Läufen erhalten.
[Zeitpläne, Effizienz, Installation und Betrieb](docs/recurring-imports.md).

## Produktkatalog mit Barcodes

[Produktkatalog durchsuchen](https://vps.tail179a46.ts.net:9450/products).
Open-Food-Facts-Bulk-Import mit Deutschland-Kennzeichnung, gültigen Barcodes,
Herkunft und Lizenzangaben. Produkte sind getrennt von Händlerpreisen gespeichert;
bestätigte Händlerartikel-Zuordnungen ergänzen fehlende EANs beim Lesen der Preise.
Aktualisierung wöchentlich, keine erfundenen Basispreise oder Filialverfügbarkeit.
[Endpunkte, Zuordnungen und Betrieb](docs/product-catalog.md).

## Kassenbons und laufende Überwachung

[Bedienseite](https://vps.tail179a46.ts.net:9450/tools): Kassenbon als PDF/PNG/JPEG
hochladen, OCR-Zeilen und Packungen kontrollieren, Preisabweichungen nachprüfen.
Der Tracker prüft alle 15 Minuten; Angebotsgeltung und Änderungshistorie bleiben erhalten.
[Bedienung, Endpunkte und Grenzen](docs/receipts-and-tracking.md).

## Tatsächliche Datenabdeckung

| Händler | Automatische Daten | Weitere Preise |
| --- | --- | --- |
| ALDI Nord | Öffentlich beworbene Angebote der aktuellen Woche | Normalpreise per Import |
| ALDI Süd | Explizit datierte Wochenangebot-Highlights | Weitere „ab“-Angebote ohne belegtes Enddatum werden ausgelassen |
| PENNY | Aktuelle und veröffentlichte nächste Woche; regionale Angebote pro Filiale/PLZ | App-Preise separat; Mengenaktionen werden ausgelassen |
| Kaufland | Öffentlich beworbene Angebotsauswahl | Card-Preise separat; Mengenaktionen werden ausgelassen |
| Lidl | Aktuelle und veröffentlichte nächste Aktionsprospekte als durchsuchbarer Text | Keine automatisch verifizierten Produktpreise aus dem PDF |
| REWE | Gemeinsamer Browser / geprüfter Browserimport; Serverabrufe können HTTP 403 liefern | Marktgebundene Angebotskarten mit Kaufpreis und separatem Bonus-Guthaben; kein vollständiges Sortiment |
| tegut | Noch kein automatischer Adapter | Aktueller regionaler KW40-PDF einmalig eingelesen, Textsuche |
| GLOBUS, Combi, HIT, NORMA | Öffentliche Angebotsrubriken täglich | Teilangebote; Marktgeltung bzw. Onlinepreise gesondert ausgewiesen |
| dm | Öffentliche Produktsuche, begrenzte Fortsetzung alle 30 Minuten | Onlinepreise mit EAN, HTTP-429-Abkühlpause |
| EDEKA, ROSSMANN | Geprüfte öffentliche Browserimporte | Teilangebote, App-Bedingungen/Onlinekanal separat |
| Netto Marken-Discount | Grafinger Prospekt per Browser gefunden und heruntergeladen | 73-seitiger PDF; noch keine verifizierte Preiszuordnung daraus |
| Weitere Händler | Je mindestens drei öffentliche Zugänge geprüft | Siehe vollständigen Händlerprüfbericht; historische/aggregierte Belege gesondert |

Der ALDI-Nord-Adapter wurde am 02.10.2026 gegen die echte Händlerseite geprüft
(260 Angebotseinträge). Es werden keine Demo-Preise automatisch erzeugt.
Direkte Abrufe der untersuchten REWE- und Netto-Angebotsseiten lieferten hier
HTTP 403. Diese Händler erscheinen im Quellenstatus als `import_only`.
Eine dokumentierte öffentliche API mit vollständigen aktuellen Preislisten aller
deutschen Supermärkte wurde nicht gefunden. Open Food Facts Open Prices bietet
eine dokumentierte API für crowdsourcierte Preisbeobachtungen, keine garantierte
aktuelle Vollabdeckung. [Quellenrecherche](docs/german-price-sources.md).
Die API ist **kein
vollständiger Katalog aller Supermarktpreise**.

Ein beworbenes Kettenangebot (`chain_advertised`) bestätigt weder Lagerbestand
noch Gültigkeit in jeder konkreten Filiale. ALDI Nord und ALDI Süd werden getrennt
behandelt. Netto bedeutet hier Netto Marken-Discount.

`netto_dog` steht separat für Netto mit Hund. Insgesamt sind 16 Händlerkennungen
für Imports unterstützt; `/v1/sources` zeigt die tatsächliche automatische Abdeckung.
`/v1/retailers` enthält zusätzlich die aktuell gespeicherten Preis-/Angebotszahlen
und Prospektseiten. Diese Zahlen schließen App-Preise aus, können mehrere Filialen
enthalten und bedeuten keine vollständige Sortimentsabdeckung.

## EAN und eindeutige Artikelidentität

Jeder Preis enthält das Feld `ean`, derzeit bei den geprüften öffentlichen
Angebotsquellen `null`. Am 02.10.2026 enthielten alle 1.375 aktuellen Einträge
(einschließlich App-/Card-Preisen) keine EAN. Die geprüften eingebetteten Daten
von ALDI Nord/Süd, PENNY und Kaufland und die zusätzlich abgerufene
[PENNY-OREO-Produktseite](https://www.penny.de/angebote/suessigkeiten-und-snacks/oreo-kekse)
lieferten keine ausdrücklichen EAN-/GTIN-Felder. Das ist eine Lücke der bisherigen
Datenquellen; die API ist noch kein nach Barcodes vollständiger Artikelkatalog.

Die automatischen Adapter übernehmen ausdrücklich am einzelnen Produkt gelieferte
`ean`, `ean8`, `ean13`, `gtin`, `gtin8`, `gtin13` oder `gtin14`, wenn genau ein
gültiger Code vorhanden ist. Mehrere unterschiedliche Codes werden nicht zu einer
einzigen EAN reduziert. Interne Artikelnummern, SKUs, Bilddateinamen und UUIDs
werden nicht als EAN interpretiert. Vorhandene Quellen liefern diese Barcodefelder
bislang nicht; diese Erweiterung füllt deshalb den bestehenden Bestand nicht auf.

Verifizierte Zuordnungen aus weiteren Datenfeeds können per `POST /v1/imports`
im vorhandenen Feld `ean` eingelesen werden. Unterstützt sind EAN-8, EAN-13 und
GTIN-14 als Zeichenketten; führende Nullen bleiben erhalten, eine ungültige
Prüfziffer wird mit HTTP 422 abgelehnt. Eine korrekte Prüfziffer bestätigt nur das
Format, nicht die Zuordnung zu einem Produkt. Exakte Suche:
`GET /v1/prices?ean=<Barcode>` bzw. `GET /v1/offers?ean=<Barcode>`.

Ein Prospektangebot mit „verschiedene Sorten“ ist häufig eine Artikelgruppe mit
mehreren EANs. Ebenso tragen lose Waren nicht immer eine Hersteller-EAN.
Für zuverlässige Artikelvergleiche wird daher ein belegter Variantenkatalog
(EAN, Sorte, Packungsgröße und Zuordnung zum Händlerangebot) benötigt.
Produktnamen und Kassenbon-Kurztexte allein belegen diese Zuordnung nicht;
die Bonprüfung verwendet weiterhin die dokumentierte menschliche Bestätigung.

## Neue Importe und beliebige PLZ

```bash
cd api
uv run python -m pricewatch_api.cli sync --postal-code 85567
uv run python -m pricewatch_api.cli sync --source penny --postal-code 10115
```

`--source all` (Standard) aktualisiert die angeschlossenen Quellen, nicht alle
deutschen Händler. `--radius-km` (Standard 30, maximal 100) und `--max-stores`
(Standard 3, maximal 20) steuern die Auswahl von Penny-Filialen. PLZ-Koordinaten
kommen von Zippopotam.us, Filialkoordinaten und Angebotsregionen von Penny.
Es handelt sich um Luftlinien vom PLZ-Mittelpunkt, keine Fahrtstrecken. Für 85567
wurden Glonn, Vaterstetten und Höhenkirchen als erste Penny-Kandidaten gefunden.

HTTP-Äquivalent: geschütztes `POST /v1/sources/penny/sync?postal_code=85567`.
Das Backend/der Worker ruft diesen Endpunkt auf; den Import-Schlüssel nicht an
App-Nutzer weitergeben. Neue PLZs werden nicht heimlich durch jede GET-Abfrage
aus dem Internet nachgeladen. Erst synchronisieren, dann lesen:

```bash
curl 'https://vps.tail179a46.ts.net:9450/v1/offers?postal_code=85567&retailer=penny'
curl 'https://vps.tail179a46.ts.net:9450/v1/areas/85567/stores'
curl 'https://vps.tail179a46.ts.net:9450/v1/offers?retailer=penny'
```

Die dritte Abfrage zeigt alle bereits gesammelten Penny-Angebote unabhängig von
der Such-PLZ. Dieselbe Filiale hat auch bei mehreren Such-PLZs nur einen eigenen
Preisbestand. Die PLZ-Abfrage schließt zugeordnete nahegelegene Filialen ein,
auch wenn deren tatsächliche PLZ abweicht. Ohne zuvor gespeicherte Zuordnung
werden keine fremden Filialpreise allein aufgrund geografischer Vermutung ausgegeben.
Allgemeine Kettenwerbung ist weiterhin erkennbar als `chain_advertised`; sie
garantiert keine Filialgeltung (z. B. ALDI Nord ist nicht automatisch in Bayern vertreten).

## Prospekte durchsuchen

`POST /v1/sources/lidl/sync` lädt den aktuell verlinkten offiziellen Aktionsprospekt,
extrahiert PDF-Text und speichert Original und Seiten. Der Standardviewer verwendet
Region 0; die Gültigkeit für eine konkrete Lidl-Filiale ist damit nicht bestätigt.
Online-Shop-Produktlinks im Prospekt werden nicht zu Lebensmittel-Filialpreisen erklärt.

```bash
curl 'https://vps.tail179a46.ts.net:9450/v1/flyers?retailer=lidl&q=Spezi'
curl 'https://vps.tail179a46.ts.net:9450/v1/flyers?q=Spezi'
```

Treffer enthalten Seite, Textauszug, unbestätigte Betragskandidaten und den Link
zum gespeicherten PDF. `price_candidates` kann auch Datumsangaben, Grundpreise
und Pfand enthalten. Solche Ergebnisse werden **nicht** als verifizierte Preise in
`/v1/prices` veröffentlicht. Eine ganze Prospektwoche ist auch kein Beleg für die
Gültigkeit jedes einzelnen Artikels an jedem Wochentag. Der tegut-PDF gilt explizit
28.09.–02.10.2026 für seine benannte Region; er wird nicht als Angebot für 85567 ausgegeben.

Weitere offizielle PDFs per geschütztem `POST /v1/flyers/import` hochladen:
Multipart-Feld `file`, Query-Parameter `title`, `retailer`, `source_url`, `valid_from`,
`valid_until`, `scope` sowie ggf. `postal_code`, `store_id`, `region_label`.
Maximal 80 MiB und 120 Seiten; Originale liegen in `PRICEWATCH_FLYER_DIR`
(Standard `api/data/flyers` bei Start im API-Ordner). Dieses Verzeichnis beim
Deployment persistent speichern. Die Datenbank speichert Text und Herkunft.
Bildseiten ohne hinreichende Textschicht erhalten `needs_ocr`, keine erfundenen Preise.
Der Python-Extractor unterstützt optional OCR mit lokal installiertem Tesseract
und Sprachdaten `deu+eng`; die HTTP-Uploads aktivieren OCR nicht automatisch.

Die sechs REWE-Grafing-Angebote sind ein ausdrücklich manuell recherchierter
Auszug aus der offiziellen Marktseite, kein automatischer vollständiger REWE-Katalog.
Bonusguthaben wird nicht vom Kassenpreis abgezogen. Der Markt ist am 03.10. geschlossen.

## Lokal starten

Voraussetzungen: Python ≥ 3.12 und `uv`.

```bash
cd api
uv sync --group dev
cp .env.example .env
# In .env einen langen zufälligen PRICEWATCH_INGEST_KEY eintragen.
uv run uvicorn pricewatch_api.main:app --env-file .env --host 0.0.0.0 --port 8000
```

Swagger: http://localhost:8000/docs, OpenAPI: http://localhost:8000/openapi.json.
SQLite wird beim Start angelegt, Daten bleiben in `api/pricewatch.db` erhalten.
Ohne Import-Schlüssel funktionieren Lesezugriffe; Schreibendpunkte antworten mit 503.
Eine `.env` wird nur mit `--env-file` geladen, nicht automatisch durch die Python-Module.

### Zugriff über Tailscale auf diesem Entwicklungsserver

Swagger: https://vps.tail179a46.ts.net:9450/docs

API-Basisadresse: `https://vps.tail179a46.ts.net:9450`.
Das zugreifende Gerät muss mit dem Tailscale-Netzwerk verbunden sein.
Der HTTPS-Proxy wurde auf diesem Server mit folgendem Befehl eingerichtet:

```bash
tailscale serve --bg --https=9450 http://127.0.0.1:8000
```

Der API-Prozess muss weiterhin auf Port 8000 laufen. Der Proxy allein startet
die API nicht. Prüfen: `curl --fail https://vps.tail179a46.ts.net:9450/health`.

Auf diesem Entwicklungsserver läuft die API inzwischen als aktivierter systemd-Dienst
`pricewatch-api-e70d379d.service`, gebunden an `127.0.0.1:8000`. Sie hängt dadurch
nicht an einer Agent-Terminalsitzung. Konfiguration: private `api/.env` (gitignored).
Nach Codeänderungen: `sudo systemctl restart pricewatch-api-e70d379d.service`.
Der Dienst zeigt auf diesen Worktree; vor dessen Entfernung den Dienst entsprechend
umstellen oder deaktivieren. Port 9448 ist inzwischen durch eine andere App belegt;
die aktuelle PriceWatch-Adresse verwendet deshalb 9450.

ALDI-Angebote einlesen (zweites Terminal, ebenfalls im Ordner `api`):

```bash
uv run --env-file .env python -m pricewatch_api.cli sync-aldi
```

Der CLI-Import benötigt keinen HTTP-Schlüssel, weil er direkt auf die Datenbank
zugreift. Für regelmäßige Aktualisierung denselben Befehl z. B. täglich per Cron
ausführen, mit absolutem Projektpfad und absolutem Pfad zu `uv`. Die API selbst
startet keinen Scheduler. Auf diesem Server läuft zusätzlich der systemd-Timer
`pricewatch-sync-e70d379d.timer`: alle 15 Minuten werden die angebundenen Quellen für
alle gespeicherten Penny-Such-PLZ sowie die Default-PLZ 85567 geprüft. Weitere
Händlerseiten werden ohne Preisimport überwacht. Dienstvorlagen liegen in `api/deploy/`.
Nur erfolgreiche, vollständig validierte Abrufe ersetzen
die aktive ALDI-Angebotsmenge; zurückgezogene Artikel werden ausgeblendet.
Bei Abruffehlern bleiben vorhandene Daten erhalten, unterliegen aber weiterhin
Gültigkeits- und Frischefiltern. Fehler und letzter Erfolg sind in `/v1/sources` sichtbar.

## Endpunkte

| Methode | Pfad | Zweck |
| --- | --- | --- |
| GET | `/health` | Datenbank und Tabellen erreichbar |
| GET | `/v1/retailers` | Unterstützte Händlerkennungen |
| GET | `/v1/sources` | Automatische/Import-Quellen und letzter Importstatus |
| GET | `/v1/prices` | Normalpreise und Angebote |
| GET | `/v1/offers` | Nur Angebote |
| POST | `/v1/imports` | Validierten Preisbatch übernehmen, Bearer-Token erforderlich |
| POST | `/v1/sources/aldi_nord/sync` | ALDI jetzt abrufen, Bearer-Token erforderlich |

Leseabfragen unterstützen `q`, `retailer`, `ean`, `on` (ISO-Datum), `postal_code`,
`store_id`, `include_membership`, `max_age_days`, `limit` und `offset`.

```bash
curl 'http://localhost:8000/v1/offers?q=Bananen&retailer=aldi_nord'
curl 'http://localhost:8000/v1/prices?q=Spezi&postal_code=10115&store_id=rewe-123'
curl 'http://localhost:8000/v1/sources'
```

Antwortformat: `{ "items": [...], "total": 123, "limit": 50, "offset": 0 }`.
Standardmäßig gelten nur am angefragten Datum gültige, innerhalb der letzten
7 Tage beobachtete Preise; Mitgliedschaftspreise sind ausgeschlossen. `on`
verwendet ohne Angabe den heutigen Tag in Europe/Berlin. `max_age_days` ist
zwischen 1 und 365 einstellbar. Sortierung: Packungspreis aufsteigend, dann ID.
Packungspreis-Sortierung ersetzt **keinen** Vergleich auf identischer Mengenbasis.

Bei einer PLZ-Abfrage werden passende PLZ-Angebote, beworbene Kettenangebote
und zuvor zugeordnete Filialen geliefert. Filialpreise können außerdem mit einer
expliziten `store_id` abgefragt werden. Ohne Standortfilter werden alle Bereiche
geliefert; jedes Ergebnis trägt seinen `scope`. Das Filialverzeichnis ist bisher auf die importierten Penny-Filialen und den
manuell dokumentierten REWE-Markt beschränkt; Fahrtstrecken werden nicht berechnet.

`q` ist eine Suche im Artikelnamen, inklusive Umlaut-Normalisierung; kein semantisches
Matching (z. B. „Wasser“ ≠ automatisch jede Mineralwasser-Marke). Eine EAN kann
identische Produkte verbinden, sofern die Quelle sie liefert. Unterschiedliche
Packungsgrößen oder Obstsorten werden nicht automatisch als identisch angesehen.

## Händlerdaten importieren

`Authorization: Bearer <PRICEWATCH_INGEST_KEY>` schützt beide Schreibendpunkte.
Der Schlüssel gehört ausschließlich in Backend/Worker, niemals in die iOS-App.

Beispiel für das **Format**, keine echten REWE-Preise; Datum, Quelle und Werte
müssen durch tatsächlich erhobene Daten ersetzt werden:

```json
{
  "source": "my_verified_feed",
  "prices": [{
    "retailer": "rewe",
    "source_product_id": "supplier-product-123",
    "name": "Äpfel Elstar",
    "kind": "offer",
    "price_cents": 199,
    "regular_price_cents": 249,
    "deposit_cents": 0,
    "currency": "EUR",
    "package_label": "2 kg",
    "unit_price_cents": "99.50",
    "unit_price_unit": "kg",
    "valid_from": "2026-10-01",
    "valid_until": "2026-10-03",
    "scope": "store",
    "store_id": "rewe-123",
    "postal_code": "10115",
    "requires_membership": false,
    "source_url": "https://www.rewe.de/angebote/",
    "observed_at": "2026-10-02T08:00:00+02:00"
  }]
}
```

Die Payload als `prices.json` speichern und mit gültigem Token senden:

```bash
curl -X POST 'http://localhost:8000/v1/imports' \
  -H "Authorization: Bearer $PRICEWATCH_INGEST_KEY" \
  -H 'Content-Type: application/json' --data-binary @prices.json
```

Der Token muss hierfür in der Shell gesetzt sein; der API-Start mit `--env-file`
setzt ihn nicht im aufrufenden Terminal. Swagger erlaubt ebenfalls den Import
über das Headerfeld `authorization` (vollständiger Wert `Bearer ...`).

Bis zu 1.000 Einträge pro Batch. Ein ungültiger Eintrag lehnt den gesamten Batch
ab. Gleiche Quelle, Händler, Quellartikel, Preisart, Standort und Startdatum ergeben
dieselbe ID; wiederholte Imports erzeugen keine Duplikate. Ältere Beobachtungen
überschreiben keine neueren. `processed` zählt unterschiedliche validierte IDs,
nicht zwingend tatsächlich geänderte Zeilen. Feed-Imports sind inkrementell;
ein ausgelassener Artikel wird dadurch nicht automatisch entfernt. Quellen müssen
korrekte Gültigkeitsintervalle liefern. `aldi_nord` ist als Quellenname reserviert.

Geldwerte sind EUR-Cent. Packungspreise sind Ganzzahlen, Grundpreise dürfen
Cent-Bruchteile enthalten (`99.50` Cent/kg = 0,995 EUR/kg). Pfand ist separat;
`checkout_price_cents` enthält Preis + Pfand und bleibt bei unbekanntem Pfand `null`.
Grundpreise werden nur aus expliziten Quellenangaben übernommen, nicht aus
mehrdeutigen Packungstexten geraten. Eine UVP ist kein Händler-Normalpreis und
wird beim ALDI-Import nur als Referenz in `conditions` geführt.

## Supabase/PostgreSQL

Die Migrationen `supabase/migrations/0004_price_catalog.sql` und
`supabase/migrations/0005_regional_stores_and_flyers.sql` über den bestehenden
Supabase-Migrationsweg anwenden. Für PostgreSQL legt die Anwendung Tabellen
absichtlich nicht automatisch an. `DATABASE_URL` auf die direkte PostgreSQL-
oder Session-Pooler-Verbindung setzen (mit TLS). Zugangsdaten nur serverseitig
speichern. Der Backend-Datenbankbenutzer braucht Schreibrechte auf `price_catalog`
und `price_source_runs`; die Migration erlaubt keine direkten anon-/App-Zugriffe.

Die bestehenden iOS-Views lesen weiterhin die alte Tabelle `offers` inklusive
deren bestehender Demo-Daten. Diese neue API liest und schreibt ausschließlich
`price_catalog`; sie ist noch nicht an die iOS-Ansichten angeschlossen.
Die bisherigen Einkaufslisten werden nicht verändert. Ein vollständiger
Warenkorbvergleich mit Fahrtkosten und Routenplanung ist der nächste Ausbauschritt.

Für externes Hosting HTTPS und Zugriffsbeschränkung/Rate-Limits auf die
Importendpunkte im Reverse Proxy konfigurieren. Der ALDI-Adapter benötigt
ausgehendes HTTPS. Es ist kein Cloud-Deployment durchgeführt worden.

## Prüfen

```bash
cd api
uv run pytest -q
uv run ruff check .
cd tests/browser
npm ci
npm test
```

Die Tests verwenden temporäre Datenbanken und einen kleinen Ausschnitt der
echten ALDI-Antwort als Parserfixture. Reguläre Tests greifen nicht aufs Internet zu.
Optionaler PostgreSQL-/RLS-Test: `PRICEWATCH_TEST_DATABASE_URL` auf eine
**wegwerfbare Testdatenbank** mit bereits angewandter Migration und den Rollen
`anon`, `authenticated`, `service_role` setzen; dieser Test ersetzt die Testkatalogdaten.

GitHub Actions führt diese Prüfungen bei Pushes und Pull Requests automatisch aus.
Der Python-Job verwendet eine frische PostgreSQL-16-Datenbank, legt mit
`tests/postgres-roles.sql` ausschließlich Testrollen an und spielt die
Backend-Migrationen 0004–0009 ein. Dadurch wird der PostgreSQL-/RLS-Test in CI
nicht übersprungen. Die iOS-/Supabase-Migrationen 0001–0003 und die manuelle
iOS-Abnahme sind davon getrennt.

Der [regelmäßige REWE-Abholpreisimport](docs/rewe-recurring.md) ergänzt den
manuellen Browserimport um einen begrenzten, marktbezogenen Abruf mit Fehlerpause.
Der Sortimentscrawler importiert zusätzlich nicht rabattierte Artikel und setzt
unvollständige Durchläufe per Checkpoint fort. Der erste produktive Durchlauf
erfasste 14.702 Artikel für den Abholmarkt 461766 / PLZ 85567.


## Ergänzende externe Preisbeobachtungen

Die Preise der genannten Sammel-CSV, der REWE-Snapshots sowie direkte Abrufe
von Open Prices, dm und Marktguru stehen unter `/v1/price-observations` und in
den Produktdetails (`price_observations`). Herkunft und Preisdatum werden
erhalten; historische/ungeografische Daten sind keine aktuellen Filialangebote.
Details: [Quellen und Aktualisierung](docs/additional-data-sources.md).


## REWE im gemeinsamen Browser

`/rewe-import` enthält den aktualisierten Lesezeichen-Export. Er liest die offiziellen
REWE-Angebotskarten, lädt sie durch Scrollen nach und meldet ungeladene oder
mehrdeutige Karten. JSON-LD-Produktseiten bleiben unterstützt. Interne NAN-IDs sind
keine EANs. Bonus-Guthaben (Euro oder Prozent) bleibt getrennt vom Kaufpreis.

Der Agent kann denselben Export im verbundenen T3-Browser ausführen: vor der
Ausführung `window.__pricewatchCollectOnly = true` setzen, danach
`window.PriceWatchReweExporter.loadMore(20)` bis `finished` aufrufen und
`collect()` in kleinen Teilmengen auslesen. Zugangsdaten oder Cookies werden
nicht ausgelesen. Der Import-Schlüssel bleibt ausschließlich auf dem Server.

`POST /v1/rewe/browser-prices` benötigt Operator-Authentifizierung und bestätigte
Markt-/Einkaufsart-Zuordnung. Alle Preise werden als Beobachtungen gespeichert.
Explizit datierte, marktgleiche Angebote mit bekannter Mitgliedschaftsbedingung
und Einkaufsart `advertised` erscheinen zusätzlich unter `/v1/offers` und
`/v1/prices`. Abhol-/Lieferpreise werden nicht als Filialangebote übernommen.
Die Antwort nennt `processed` und `published_offers`. Quellenlose Bonus-Aktionen
ohne Kaufpreis bleiben ausgeschlossen. Der Browser muss für neue Erfassungen
verbunden sein; dies beseitigt nicht die REWE-Sperre bei direkten Serverabrufen.

Export-Regressionstests mit echten REWE-Karten:

```bash
cd api/tests/browser
npm ci --ignore-scripts
npm test
```
