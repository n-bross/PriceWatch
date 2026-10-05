# Regelmäßiger REWE-Abholpreisimport

## Sortimentsimport (aktiv seit 04.10.2026)

`pricewatch_api.rewe_catalog` ergänzt den unten beschriebenen Angebotsabruf um
reguläre Artikel. Der Import entdeckt die 16 öffentlichen Sortimentskategorien
für den konfigurierten Abholmarkt und ruft sie ohne Rabattfilter ab. Redaktionelle
Themensammlungen werden ausgelassen; doppelte Artikel über Kategorien werden
innerhalb eines Durchlaufs anhand der Produkt-/Artikel-ID zusammengefasst.

```bash
uv run --env-file .env python -m pricewatch_api.rewe_catalog \
  --market-id 461766 --postal-code 85567 --max-pages 40
```

Jeder Lauf verarbeitet maximal 40 Seiten (konfigurierbar bis 100). Erfolgreiche
Seiten werden sofort gespeichert; `catalog.json` und `catalog.lock` im Markt-
Unterverzeichnis ermöglichen die Fortsetzung nach einem Neustart. Fehler bleiben
sichtbar und lösen eine sechs Stunden lange Pause aus. Eine Kategorie mit 10.000
oder mehr Suchtreffern wird als mögliche Suchbegrenzung gemeldet, nicht als
vollständig importiert ausgegeben. `Retry-After` gilt zusätzlich im HTTP-Cache.

Nach einem abgeschlossenen Durchlauf wird frühestens nach 24 Stunden neu begonnen.
`pricewatch-rewe-catalog.timer` startet alle 15 Minuten einen begrenzten Lauf.
Die Vorlagen verwenden `@API_DIR@` für den Programmstand und `@DATA_API_DIR@` für
das Verzeichnis mit `.env`, Datenbank und Checkpoints. Die Marktparameter sind
im Service für 461766 / 85567 voreingestellt und können über die Environment-Datei
angepasst werden.

Erster vollständiger Lauf: **14.702 unterschiedliche Artikel über 381 Seiten aus
16 Kategorien** in der laufenden Datenbank. Das ist der entdeckte Abholkatalog
dieses Marktes, keine Zusage aller Filialpreise oder vollständiger Warenverfügbarkeit.
Die Quelle bleibt `rewe_shop_pickup`. Der laufende Preisvergleich und der neue
iOS-Tab „Preise“ verwenden beide `/v1/compare`.

Der API-Status unter `/v1/import-status` zeigt den Durchlauffortschritt als
„REWE Abholsortiment“. Der bisherige Browserimport bleibt als eigene Quelle sichtbar.

## Separater Rabattabruf

Der Import nutzt `https://www.rewe.de/shop/api/products` mit
`serviceTypes=PICKUP`, `marketId`, `attribute=discounted` und `page`.
Jede Antwort muss Markt und Abholkanal bestätigen. Es werden höchstens 20 Seiten
pro Lauf abgerufen (konfigurierbar bis 50); überschreitet das Ergebnis diese
Grenze oder schlägt eine Seite fehl, wird der gesamte Abruf verworfen.
Bestehende Beobachtungen bleiben erhalten.

Die Quelle heißt `rewe_shop_pickup`. Ergebnisse stehen in
`/v1/price-observations?source=rewe_shop_pickup` und im Preisvergleich.
Sie sind marktbezogene Abholpreise, keine bestätigten Ladenpreise. Sie werden
deshalb nicht in `price_catalog` oder `/v1/offers` geschrieben.
Explizite GTINs werden geprüft, Artikelnummern nicht zu Barcodes umgedeutet.
Bonusguthaben wird separat gespeichert und nicht vom Kaufpreis abgezogen.
Ein unbekannter Angebotsbeginn bleibt leer. Das explizite Ablaufdatum und der
unveränderte Zeitstempel der Quelle werden gespeichert; Mitgliedschaftsbedingungen
werden nicht aus dem Vorhandensein eines Bonus abgeleitet.

## Lokal ausführen

Vom Verzeichnis `api` aus, mit `DATABASE_URL` in `.env`:

```bash
uv sync --frozen
uv run --env-file .env python -m pricewatch_api.rewe_recurring \
  --market-id 461766 --postal-code 85567
```

Markt-ID und PLZ müssen zum gewünschten Abholmarkt gehören. Die Antwort bestätigt
die Markt-ID; die PLZ wird als explizite Konfiguration übernommen. SQLite wird bei
Bedarf initialisiert; PostgreSQL benötigt vorab die Backend-Migrationen 0004–0009.

Status, bedingter HTTP-Cache und Prozesssperre liegen in
`data/rewe-shop/<Markt-ID>-<PLZ>/`. Sowohl nach Erfolg als auch nach Fehlern gilt
eine Pause von sechs Stunden. Bei 403/429 berücksichtigt der HTTP-Cache zusätzlich
`Retry-After`. Gleichzeitige Läufe für denselben Markt werden verhindert.

## Systemd vorbereiten

Die Vorlagen `deploy/pricewatch-rewe.service` und `.timer` sind separat installierbar.
In `api/.env` zusätzlich konfigurieren:

```dotenv
REWE_MARKET_ID=461766
REWE_POSTAL_CODE=85567
```

Vom Verzeichnis `api` aus auf dem Zielhost ausführen:

```bash
api_dir="$(pwd)"
for kind in service timer; do
  sed "s|@API_DIR@|${api_dir}|g" "deploy/pricewatch-rewe.${kind}" \
    | sudo tee "/etc/systemd/system/pricewatch-rewe.${kind}" >/dev/null
done
sudo systemctl daemon-reload
sudo systemctl enable --now pricewatch-rewe.timer
```

Der Timer prüft alle 15 Minuten, ob der nächste Abruf fällig ist. Ein Lauf hat
maximal 840 Sekunden Zeit. Der allgemeine Installer aktiviert diese neue Quelle
nicht automatisch, da Markt und PLZ ausdrücklich konfiguriert werden müssen.
Die Vorlagen allein bedeuten noch kein Deployment.

## Prüfen

`uv run pytest tests/test_rewe_recurring.py -q` prüft echte Antwortstrukturen,
Pagination, Fremdmarkt-/Kanalabweichungen, Preisvalidierung, Bonusbehandlung,
Fehler ohne Teilimport und Wiederholungsabstände. Netzwerkzugriffe sind gemockt.
`tests/test_rewe_catalog.py` prüft zusätzlich Wiederaufnahme, Kategorien,
Deduplizierung und die Erkennung begrenzter Suchergebnisse.
