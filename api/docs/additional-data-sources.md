# Ergänzende Quellen und Datenordnung

Stand 02.10.2026. Die vom Nutzer genannten Quellen wurden anhand ihrer
Dokumentation und abrufbaren Daten geprüft; verlinkter Drittcode wurde nicht
installiert oder ausgeführt.

| Quelle | Befund | Umgang |
| --- | --- | --- |
| [german-supermarket-prices](https://github.com/loukesio/german-supermarket-prices) | CSV mit 9.109 Zeilen, 6.428 unterschiedlichen prüfziffergültigen Barcodes; Quellen `open-prices`, `dm-website`, `marktguru-offers`; enthält historische Preise und fehlende Orts-/Geltungsangaben | Produktidentitäten, Kategorien und alle gültigen Preiszeilen werden importiert. Unbekannte Orte/Geltung bleiben unbekannt; historische Preise stehen in `/v1/price-observations`. |
| [rewe-price-data](https://github.com/L480/rewe-price-data) | Repository beschreibt zwei Marktregionen. [Downloadverzeichnis](https://rewe.nicoo.org/) listet als neuesten Snapshot 09.09.2025, nicht aktuelle tägliche Daten | Beide neuesten verfügbaren CSV-Snapshots werden als historische Preisbeobachtungen importiert; nicht als aktuelle Grafinger Preise verwenden. Das CSV-Feld `ean` enthält auch kurze interne Codes: Prüfziffer und Typ müssen kontrolliert werden. |
| [openclaw-supermarket-deals](https://github.com/benmillerat/openclaw-supermarket-deals) | Suchadapter für Marktguru-Angebote nach PLZ, keine vollständigen Sortimente; README beschreibt Laufzeitextraktion von Web-Client-Schlüsseln | Nicht als vertraglich stabile Partner-API eingeordnet. Suchadapter übernimmt Angebote für 85567 nach allen Angebotskategorien der Sammel-CSV, mit Geltungsdaten und Händler. Suchlimit/Abdeckung werden protokolliert. „Verschiedene Sorten“ belegt nicht jede einzelne EAN. |
| [Open Prices](https://prices.openfoodfacts.org/api/docs) | Offizielle API für Preisbeobachtungen, mit Datum/Ort/Beleg; ODbL | Direkter Adapter importiert Preisbeobachtungen für alle abrufbaren deutschen OSM-Orte, mit Einheit, Rabatt, Ort, Beleg-ID und ursprünglichem Preisdatum. Keine erfundenen Enddaten. |
| dm-Webseite / App | Nutzer verweist auf öffentliche Suche mit Barcodes; ein CSV-Snapshot ist vorhanden | Direkter Suchadapter übernimmt Onlinepreise und EAN. Kategorie-/Markenpartitionen erweitern die begrenzte Suchpagination; HTTP 429 und verbleibende Lücken werden protokolliert. |
| [Pepesto](https://www.pepesto.com/supermarkets/) | Anbieter nennt 28 europäische Ketten; für Deutschland aktuell REWE, weitere Ketten als Roadmap. API-Key nach kostenpflichtigem Zugang | Nicht alle deutschen Supermärkte; ohne Zugang kein aktiver Adapter. |
| [Wikipedia-Händlerliste](https://en.wikipedia.org/wiki/List_of_supermarket_chains_in_Germany) | Händlerverzeichnis | Ergänzt ein Händlerverzeichnis, enthält keine Produkte, Preise oder Marktbestände. |

## Implementierte Ordnung

- **Produkt:** exakte EAN/GTIN, Name, Marke, Packung, Quellkategorien. Barcodes
  werden als Zeichenketten behandelt. Andere Barcodelängen werden nicht geraten.
- **Quellinformationen:** Pro EAN und Quelle ein eigener Metadatensatz. Aktuelle
  Stammdaten bevorzugen Betreiberkorrektur > ausdrückliche Händlerbeobachtung >
  OFF > sekundäre CSV. Niedrigere Priorität löscht die höhere nicht. Widersprüchliche
  Namen/Packungen bleiben in `source_records` sichtbar; keine fuzzy EAN-Zuordnung.
- **Händlerartikel:** Händler + interne Kennung + gegebenenfalls Filiale. Eine
  EAN-Zuordnung muss ausdrücklich mit Beleg bestätigt werden. Herkunftstexte wie
  `reported_stores=REWE` stellen keine solche Zuordnung her.
- **Preis:** EUR-Cents, Preisart `regular`/`offer`, Pfand, Packungs-/Grundpreis,
  Filiale/PLZ, Quelle, Datum/Geltung, App-/Card-Bedingung. Geografisch unbekannte
  Beobachtungen werden nicht zu Grafinger Filialpreisen erklärt.
- **Packungsrabatt:** privat am Bonartikel, getrennt vom Händlerangebot.
- **Kategorie:** Produktart, unabhängig von Preisart. Das CSV-Präfix `Angebot ·`
  wird nicht als Produktkategorie übernommen. OFF-Tags werden als Quell-Tags
  erhalten; unterschiedliche Kategoriensysteme sind noch kein einheitlicher
  deutscher Kategorienbaum. Filter `/v1/products?category=en:beverages&brand=…`
  verwendet die gespeicherten Quellwerte exakt.

Auch unterschiedliche Packungsgrößen derselben Marke bleiben getrennte Produkte.
Äquivalente Einkaufswünsche (z. B. „Milch“) können später mehrere Produkte zulassen,
ohne deren Identität zusammenzuführen. Vergleiche verwenden dabei passende
Grundpreise (kg/l/Stück), nicht pauschal den kleinsten Packungspreis.

CSV-Produktimport:

```bash
cd api
uv run --env-file .env python -m pricewatch_api.cli catalog-import-dataset --file /pfad/prices.csv
```

Der Befehl `catalog-import-dataset` ergänzt Produktmetadaten. Der neue Befehl
`external-sync` übernimmt auch Preise, behält Quelle/Datum/Einheit bei und
speichert geografisch oder zeitlich unvollständige Datensätze getrennt von
gesichert gültigen Angeboten. Die Originaldatei bleibt als Quellenbeleg
unter `api/data/catalog` außerhalb von Git. Datum und aktuelle Verfügbarkeit
werden nicht durch die heutige Importzeit ersetzt.

## Kundenkarten und Apps

Öffentliche Produkt-/Angebotsdaten und persönliche Coupon-/Kundenkartendaten
bleiben getrennt. Für eine mögliche Kartenübersicht müssen Codeformat, Gültigkeit
und Akzeptanz pro Händler getestet werden. Kunden-Codes gehören in einen privaten
Nutzerbereich, nicht in diesen offenen Katalog; der derzeitige Betreiberzugang
ersetzt noch keine individuelle Nutzeranmeldung. Couponaktivierung und Einlösung
bleiben Händlerfunktionen, bis eine belegte Integration existiert. Hier ist noch
kein Wallet oder Login in Händlerkonten implementiert.

## Preisabruf und tägliche Aktualisierung

```bash
cd api
uv run --env-file .env python -m pricewatch_api.cli external-sync
# einzelne Quelle: --external-source dataset|rewe|dm|open_prices|marktguru
```

`GET /v1/price-observations` liefert sämtliche externen Preisbeobachtungen mit
Pagination (`limit`, `offset`) und Filtern `q`, `ean`, `retailer`, `source`,
`postal_code`. Herkunft, Preisdatum, unbekannte Geltung und Ort bleiben sichtbar.
Retailer-Werte entsprechen der Quelle (z. B. `REWE`, `dm`); `ALDI` wird ohne Beleg
nicht in Nord/Süd aufgeteilt. Lokale Barcodes erfordern einen Händlerfilter.
`GET /v1/price-observations/status` nennt die gespeicherten Zahlen je Quelle.
Produktdetails und `/v1/products/{ean}/prices` enthalten zusätzlich
`price_observations`; `/products` zeigt diese beim Produkt an.

`/v1/prices` und `/v1/offers` behalten ihre Filter für belegte Geltung. Ein alter
Snapshot ohne Markt/Enddatum wird dadurch nicht zu einem aktuellen Filialpreis.
Der Timer `pricewatch-external-e70d379d.timer` startet die Quellen täglich um
05:00 Uhr Europe/Berlin plus maximal 15 Minuten Zufallsverzögerung.

Wikipedia liefert Händlernamen und Pepesto erfordert einen Kundenzugang; für
beide werden keine fiktiven Produktpreise angelegt.

## Fortsetzbarer dm-Import und REWE-Browserpreise

Der dm-Adapter verarbeitet pro Lauf höchstens zehn Suchseiten mit drei Sekunden
Abstand. Nach HTTP 429 pausiert er gemäß `Retry-After` (mindestens fünf Minuten;
ohne Angabe eine Stunde). Bei 401/403 pausiert er standardmäßig einen Tag. Der
Checkpunkt `data/catalog/dm-progress.json` speichert Seiten, Kategorien/Marken,
gesehene Artikel und nächsten Versuch. Wiederholungen sind dedupliziert.
`pricewatch-dm-e70d379d.timer` prüft alle 30 Minuten, ob der nächste Stapel fällig
ist; innerhalb der Wartezeit erfolgen keine Händlerabrufe. Fortschritt steht in
`/v1/price-observations/status` unter `dm_progress` und im Produktkatalog.
Ein vollständiger Zyklus wird frühestens einen Tag nach Abschluss neu gestartet.
Die berichtete Suchindexgröße ist keine Zusage vollständiger Abdeckung.

REWE blockiert im aktuellen Server-/Chromium-Test sowohl `/shop/` als auch die
Grafinger Angebotsseite mit HTTP 403, WAF Challenge / Bot protection. Die vom
Nutzer bestätigte Seite ist die Filial-Angebotsseite für Markt 461766; dies
bestätigt noch keinen Zugang zum vollständigen Liefer-/Abholsortiment.

`/rewe-import` stellt einen lokalen Lesezeichen-Export und eine geprüfte
Importmaske bereit. Der Export liest ausschließlich JSON-LD-Produkte mit
ausdrücklichem EUR-Angebotspreis und exportiert keine Cookies/Zugangsdaten.
Ob die konkrete Händlerseite solche strukturierten Preise liefert, ist auf
der erreichbaren Nutzersitzung noch zu prüfen. Ohne diese Daten meldet der
Export ausdrücklich einen leeren Befund; DOM-/Preisheuristiken werden nicht
als geprüfte Preise importiert. Er exportiert nicht automatisch alle Kategorien.

`POST /v1/rewe/browser-prices` erfordert den vorhandenen Betreiber-Importschlüssel,
explizite Kontextbestätigung, Markt, PLZ, Einkaufsart und tatsächliches
Erfassungsdatum. `advertised`, `pickup`, `delivery`, `store` bleiben getrennt;
Angebotsdaten werden nur übernommen, wenn sie in der Quelle vorliegen. Kein
erfundenes Enddatum, keine automatische Händlerartikel-zu-EAN-Umrechnung.
Diese Browserbeobachtungen stehen im externen Preisbestand als `rewe_browser`.
