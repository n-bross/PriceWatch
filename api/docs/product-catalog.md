# Produktkatalog und Händlerartikel-Zuordnungen

Bedienseite: https://vps.tail179a46.ts.net:9450/products

Der Produktkatalog ist getrennt vom zeitlich und regional gültigen Preisbestand.
Die erste Datenquelle ist der offizielle komprimierte TSV-Export von Open Food
Facts. Es werden Datensätze mit dem Länder-Tag `en:germany`, nichtleerem Namen
und gültiger EAN-8/EAN-13/GTIN-14-Prüfziffer importiert. Länder-Tags und
Händlerangaben (`reported_stores`) sind Community-Metadaten. Sie belegen weder
ein aktuelles Sortiment noch die Verfügbarkeit in einer Filiale. Der Katalog
ist nicht vollständig; Non-Food, lose Ware und Artikel ohne unterstützten Barcode
sind durch diesen Import nicht vollständig abgedeckt. UPC-12 und Codes mit
ungültiger Prüfziffer werden nicht automatisch umgedeutet.

## Quellen und Nutzung

- Produktdaten und Bulk-Export: [Open Food Facts](https://world.openfoodfacts.org/data).
- [API-Dokumentation](https://openfoodfacts.github.io/openfoodfacts-server/api/)
  empfiehlt Bulk-Exporte für mehr als einige hundert Produkte.
- Datenbanklizenz: [ODbL 1.0](https://opendatacommons.org/licenses/odbl/1-0/),
  einzelne Inhalte DbCL. Attribution und Lizenzlink werden mit OFF-Produkten
  und im Katalogstatus ausgegeben und auf der Bedienseite angezeigt.
  Bei Weiterverwendung eines abgeleiteten Katalogs gelten die ODbL-Bedingungen.
- Bilder werden nicht heruntergeladen. Bei Produkten bleiben Quelle, Quelländerung
  (`source_updated_at`) und eigene Importzeit (`imported_at`) erhalten.
- EAN-Prüfziffern bestätigen das Format, nicht die von GS1 verifizierte Identität.

## Endpunkte

| Methode | Pfad | Zweck |
| --- | --- | --- |
| GET | `/v1/products?q=Spezi&limit=50&offset=0` | Produktnamen durchsuchen; paginierter Katalog |
| GET | `/v1/products?ean=<Barcode>` | Exakte Barcode-Suche, führende Nullen erhalten |
| GET | `/v1/products/{ean}` | Produktdaten, Provenienz und bestätigte Artikelzuordnungen |
| GET | `/v1/products/{ean}/prices?kind=regular&postal_code=85567` | Belegte Normalpreise; dieselben Ort-/Datum-/App-Filter wie `/v1/prices` |
| GET | `/v1/products/status` | Produktzahl, Zuordnungszahl, Importstatus und Abdeckungsgrenzen |
| POST | `/v1/products/import` | Geschützter Import verifizierter Produktdaten |
| PUT | `/v1/retailer-products` | Geschützte, bestätigte Zuordnung Händlerartikel → EAN |
| DELETE | `/v1/retailer-products?retailer=rewe&source_product_id=…&store_id=…` | Geschützte Korrektur durch Löschen einer Zuordnung |

Die schreibenden Endpunkte benötigen den vorhandenen Bearer-Importschlüssel.
Ein zusätzlicher Produktimport hat die Form `{"products": [...]}` mit `ean`,
`name`, `countries` (Liste von Quell-Tags), `source_url` und optional `brand`,
`package_label`, `source_updated_at` (mit Zeitzone). Diese Produkte werden als
`verified_import` gekennzeichnet; der Betreiber muss die Identität verifizieren.
Bei Preisimporten mit ausdrücklicher EAN wird ein noch unbekanntes Produkt mit
Herkunft `retailer_observation` ergänzt. Preisimporte überschreiben keine
vorhandenen Produktstammdaten. Betreiberkorrekturen werden von OFF-Updates
nicht überschrieben.

## Händlerartikel zuordnen

Beispielstruktur (kein realer Artikelnachweis):

```json
{
  "retailer": "rewe",
  "source_product_id": "interne-artikelnummer-aus-der-preisquelle",
  "store_id": "461766",
  "ean": "Barcode der kontrollierten Packung",
  "source_url": "https://example.org/beleg-zur-artikelidentitaet",
  "note": "Marke, Sorte und Packungsgröße kontrolliert",
  "identity_confirmed": true,
  "observed_at": "2026-10-02T16:00:00+00:00"
}
```

Die EAN muss im Katalog existieren. Namenähnlichkeit oder ein Prospekt mit
„verschiedenen Sorten“ reicht nicht als Identitätsnachweis. `source_product_id`
ist die Kennung in der Preisquelle, nicht die PriceWatch-Preis-UUID. Bonnummern
und Web-Angebots-UUIDs sind nicht automatisch dieselbe Händlerkennung.
Ohne `store_id` gilt die bestätigte Identität für dieselbe Händlerkennung
kettenweit. Filialspezifische Zuordnungen haben Vorrang. Händlercodes können
wechseln oder wiederverwendet werden; Zuordnungen deshalb nur mit belastbarem
Nachweis setzen und bei Änderungen berichtigen. Ältere Bestätigungen überschreiben
keine neueren. Quellenbelege sind öffentlich im Produktdetail sichtbar; hier keine
privaten Bon-URLs oder personenbezogenen Informationen hinterlegen.

`/v1/prices` und `/v1/offers` lösen die EAN beim Lesen auf. `ean_origin` unterscheidet
`source` und `confirmed_mapping`. Eine EAN der ursprünglichen Preisquelle hat
immer Vorrang. Die Rohdaten und Preisänderungshistorie werden durch die Zuordnung
nicht umgeschrieben. Auch Barcode-Suchabfragen berücksichtigen die Bestätigung.

## Preise und Verfügbarkeit

Ein Produktimport erzeugt keine Preise. Belegte Normalpreise verwenden im
bestehenden Preisbestand `kind=regular`, Angebotspreise `kind=offer`; Ort,
Beobachtungsdatum, Gültigkeit und Beleg bleiben erhalten. Ein deutschlandweiter
Basispreis wird nicht aus Community-Produktdaten oder UVPs erfunden. Zusatzrabatte
auf einzelne Packungen bleiben separate Bonbeobachtungen.

## Aktualisierung und Betrieb

```bash
cd api
uv run --env-file .env python -m pricewatch_api.cli catalog-sync
```

`pricewatch-catalog-e70d379d.timer` aktualisiert den Katalog sonntags ab 04:00
Europe/Berlin mit bis zu 15 Minuten Zufallsversatz. Angebotsprüfungen laufen weiter
alle 15 Minuten. `PRICEWATCH_CATALOG_DIR` (Standard `./data/catalog`) enthält den
komprimierten Export, HTTP-Validatoren und den Prozess-Lock. Ein Import verwendet
begrenzte Speicher-Batches und schreibt nur den komprimierten Download auf Platte.
Der initiale Export beträgt rund 1,3 GB; Updates laden bei geänderter Quelle erneut
den Export. Bei unverändertem ETag wird der Download/Import ausgelassen.

Die Aktualisierung ergänzt und aktualisiert bekannte Produkte. Nicht mehr im
Export enthaltene Artikel werden nicht automatisch gelöscht: sie können weiterhin
verkauft werden; die Quelländerungs- und Importzeit bleiben beim Produkt sichtbar.
Ein unterbrochener Import kann bereits gültige Batches gespeichert haben; sein
Status ist dann ein Fehler und der erneute Import ist idempotent. Die Detailangaben
sind keine Zusage, dass das Produkt gegenwärtig verkauft wird.

Für PostgreSQL/Supabase muss zusätzlich `0007_product_identities.sql` angewendet
werden. SQLite legt die neuen Tabellen beim Start an. Rohdateien bleiben unter
`api/data` und werden nicht ins Git-Repository aufgenommen.

## Datenordnung und lokale Barcodes

`source_records` enthält die Metadaten je EAN und Quelle; zusätzliche Quellen
überschreiben keine höher priorisierten Stammdaten. Die Kategorien der Quelle
stehen unter `categories` und sind exakt filterbar, beispielsweise
`/v1/products?category=en:beverages&brand=Paulaner`. Es gibt noch keinen einheitlich
übersetzten deutschen Kategorienbaum. [Zusätzliche Quellen und Ordnung](additional-data-sources.md).

`barcode_scope` unterscheidet globale Kandidaten von `restricted_circulation`.
Nach den [GS1-Spezifikationen](https://www.gs1.org/docs/barcodes/GS1_General_Specifications.pdf)
sind RCN-8-Präfixe 0/2 sowie entsprechende RCN-13-Bereiche 02 und 20–29 nicht als
weltweit eindeutige Artikelidentität zu behandeln. Solche Quellcodes bleiben im
Katalog gekennzeichnet. Eine Preisabfrage über diese Nummer verlangt zusätzlich
`retailer`, andernfalls HTTP 422; kein globaler Vergleich aus einer zufällig
identischen lokalen Nummer. `global_candidate` bestätigt ebenfalls noch keine
GS1-verifizierte Produktidentität. Für einen Händlerartikel ist die bestätigte
Zuordnung einschließlich Packung und Variante maßgeblich.
