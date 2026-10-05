# Kassenbons prüfen und Angebote überwachen

Die Bedienseite läuft unter `https://vps.tail179a46.ts.net:9450/tools` im Tailscale-Netz.
Upload, Lesen, Prüfen und Löschen von Bons benötigen den bestehenden
`PRICEWATCH_INGEST_KEY` aus der privaten `api/.env`. Die Seite speichert den Schlüssel
nicht im Browser-Speicher. Öffentliche Angebotsabfragen benötigen keinen Schlüssel.

## Bon-Abgleich

1. Supermarkt, Kaufdatum, Such-PLZ und tatsächliche Filial-ID kontrollieren.
2. PDF, PNG oder JPEG hochladen (20 MiB, maximal acht Seiten).
3. Die lokale OCR schlägt Produktzeilen vor. Bei PDFs wird eine vorhandene
   Textschicht bevorzugt. Foto-OCR verwendet lokal Tesseract mit `deu+eng`;
   Bilder werden nicht an einen externen KI-Anbieter geschickt.
4. Namen, bezahlte Produkt-Gesamtbeträge, Stückzahl bzw. kg/l und App-/Card-Preise
   prüfen. Pfand, Summen und separat gedruckte Rabatte werden nicht als Artikel
   übernommen. Separate Rabattzeilen können dem einzelnen Artikel noch nicht
   automatisch zugeordnet werden. Den tatsächlichen Netto-Produktbetrag prüfen.
5. Passenden Katalogeintrag wählen und gleiche Packungsgröße/Variante bestätigen.
   Anschließend „Bonangaben … kontrolliert“ aktivieren und Preise vergleichen.

Bei eindeutig gleichem Namen wird direkt ein vorläufiger Preisvergleich angezeigt
(`provisional_*`). Packung, Menge und OCR müssen trotzdem bestätigt werden.
Unbekannte Bon-Abkürzungen und ähnliche Namen ergeben zunächst Vorschläge, keine
behauptete Produktidentität. Für fehlende oder mehrdeutige Artikel bleiben offene
Prüffälle sichtbar. Zusätzliche Zeilen und OCR-Korrekturen sind in der Seite möglich.
Bei Gewichtsware wird mit dem kg-/Liter-Grundpreis gerechnet, bei Packungen mit
Stückzahl × Packungspreis. Bis zu einem Cent Rundungsdifferenz wird toleriert.

Zusatzrabatte lassen sich pro Bonzeile manuell erfassen: In „Bezahlt“ steht der
Netto-Zeilenbetrag nach Rabatt, unter „Zusatzrabatt“ der Gesamtbetrag vor Rabatt,
optional der Prozentsatz sowie Packungsaufkleber, Coupon, Artikelaktion oder
ungeklärte Rabattart. Der ursprüngliche Zeilenbetrag wird mit dem Katalog
verglichen; die Ersparnis bleibt separat gespeichert. Ohne Katalogzuordnung wird
der Rabatt trotzdem am Bon gespeichert, der Ausgangspreis bleibt ungeprüft.
Ein ausgewiesener Prozentsatz muss zu beiden Beträgen passen (ein Cent Toleranz).
Ein Packungsrabatt gilt nur für diese Bonbeobachtung und wird nicht als öffentliches
Angebot mit angenommener Gültigkeitsdauer veröffentlicht. Der Bonbetrag vor dem
Zusatzrabatt kann bereits ein Angebotspreis sein, er ist kein belegter Normalpreis.

API-Feld einer Bonzeile, Beispiel 8,99 € vor Rabatt und 6,29 € tatsächlich bezahlt:

```json
{
  "paid_total_cents": 629,
  "discount": {
    "original_total_cents": 899,
    "percent": "30",
    "kind": "sticker",
    "note": "Zusätzlicher Rabatt auf die einzelne Packung"
  }
}
```

`discount` ist optional; `kind` erlaubt `sticker`, `coupon`, `article_promotion`,
`other`. Beim Vergleich werden `compared_total_cents` (vor Zusatzrabatt),
`paid_total_cents` (danach) und `discount_cents` getrennt ausgegeben. Prozent- und
Rabattzeilen aus OCR werden weiterhin nicht automatisch einem Artikel zugeordnet.

Der Vergleich verwendet das Kaufdatum und die tatsächliche Filial-ID. Angebote
benachbarter Filialen werden nicht eingesetzt. Allgemeine Werbung hat eigene
Statuswerte `advertised_match` / `advertised_difference`, weil die Filialgeltung
nicht gesichert ist. `match` / `mismatch` beziehen sich auf einen gespeicherten
Eintrag der konkreten Filiale. `needs_review`, `not_found`, `invalid_selection`
und `unit_unknown` benennen ungeklärte Fälle. Ein Bon beweist außerdem keine
künftige Angebotsdauer oder den Normalpreis vor/nach dem Kauf.

Bestätigte Abweichungen und fehlende Artikel werden in `price_receipt_rechecks`
für eine Quellenprüfung gespeichert. Der Tracker aktualisiert die angebundenen
Quellen und vergleicht den Bon erneut. Das Ergebnis ist `resolved` oder
`unresolved`; Abruffehler lassen die Anfrage für einen späteren Versuch offen.
Ohne automatischen Händleradapter bleibt manuelle Quellenprüfung notwendig.
Bonpreise überschreiben keine Händlerangebote. Auch neue Artikel werden zunächst
als Bonbeobachtung/Prüffall gespeichert, nicht als ungeprüfte allgemeine Preisliste.

Bontext, Zeilen und Prüfresultate liegen in der geschützten Tabelle `price_receipts`,
Originaldateien in `PRICEWATCH_RECEIPT_DIR` (Standard `api/data/receipts`). Alle
Bon-Endpunkte benötigen den Schlüssel. „Bon löschen“ entfernt Tabelleintrag,
Originaldatei und offene Nachprüfung. Keine Boninformationen in öffentlichen
Tracker-Antworten. Aktuell ein gemeinsamer Betreiberzugang, keine separaten
Benutzerkonten/Mandanten.

| Methode | Pfad | Zweck |
| --- | --- | --- |
| POST | `/v1/receipts` | Multipart-Upload `file`; optionale Query-Metadaten `retailer`, `purchase_date`, `postal_code`, `store_id` |
| GET | `/v1/receipts` | Gespeicherte Bons auflisten |
| GET | `/v1/receipts/{id}` | OCR, Zeilen, Vergleich und Nachprüfstatus |
| PUT | `/v1/receipts/{id}/review` | Korrigierte Metadaten/Zeilen und Bestätigungen speichern, erneut vergleichen |
| DELETE | `/v1/receipts/{id}` | Bon einschließlich Original entfernen |

Review-Beispiel (Schlüssel per Authorization Bearer):

```json
{
  "retailer": "penny",
  "purchase_date": "2026-10-02",
  "postal_code": "85567",
  "store_id": "565668",
  "confirmed": true,
  "lines": [{
    "name": "OREO Kekse",
    "paid_total_cents": 258,
    "quantity": "2",
    "quantity_unit": "item",
    "catalog_price_id": "UUID des identischen Katalogprodukts",
    "identity_confirmed": true,
    "membership_used": false,
    "needs_quantity_review": false
  }]
}
```

## Automatische Aktualisierung

`pricewatch-sync-e70d379d.timer` startet alle 15 Minuten mit bis zu 30 Sekunden
Zufallsversatz den Worker `python -m pricewatch_api.cli track`.
Ein Prozess-Lock verhindert parallele Trackerläufe für dieselbe Datenbank.
Bei Serverneustarts holt systemd einen verpassten Termin nach.

- ALDI Nord, ALDI Süd, Penny und Kaufland: strukturierte Angebotsdaten werden
  erneut gelesen, validiert und als Snapshot importiert. Penny berücksichtigt
  alle bereits gespeicherten Such-PLZ sowie neue PLZ aus Bon-Nachprüfungen.
  Default-PLZ ist 85567. Aktuelle und explizit datierte nächste Wochen werden
  eingelesen; Prozentkampagnen ohne Europreis und Mengenaktionen ausgelassen.
- Lidl: aktuelle und bereits verlinkte nächste Aktionsprospekte. URL, Metadaten
  und CDN-ETag/Last-Modified werden geprüft. Unveränderte PDFs werden nicht
  nochmals heruntergeladen; ohne CDN-Validator mindestens alle sechs Stunden.
  Prospekttexte bleiben ungeprüft, keine automatische Preis-Produkt-Zuordnung.
- Weitere elf Händler: feste offizielle Seiten werden mit ETag/Last-Modified
  und Fingerabdruck aus sichtbarem Text/Prospektlinks überwacht. `watch_only`
  bedeutet ausdrücklich Seitenüberwachung ohne automatischen Preisimport.
  Seitenänderungen können auch redaktionell sein. HTTP 403 wird als `blocked`
  sichtbar, andere Fehler als `error`; fehlende Daten werden nicht erfunden.
  Bei REWE wird derzeit die Grafinger Marktseite überwacht, nicht jeder Markt.

`valid_from` / `valid_until` sind die vom Händler belegte Angebotsgeltung.
`observed_at` ist die Abrufzeit. Zukunftsangebote werden vor dem Startdatum bei
Standardabfragen ausgeblendet; `on=YYYY-MM-DD` erlaubt den Blick auf den jeweiligen
Tag. Bei Rücknahmen oder Preisänderungen bleiben alte Beobachtungen in der neuen
Änderungshistorie erhalten. Die Historie beginnt mit dieser Erweiterung; frühere
Preisänderungen werden nicht nachträglich erfunden. Unveränderte Abrufe erzeugen
keine weiteren Preisversionen, erneuern aber den Frische-Zeitstempel.

| Methode | Pfad | Zweck |
| --- | --- | --- |
| GET | `/v1/tracker` | Letzte Prüfung, letzte Änderung, Modus und Fehler je Quelle/PLZ |
| GET | `/v1/tracker/changes` | Zuletzt erfasste Angebotsänderungen einschließlich Gültigkeitsdaten |
| GET | `/v1/prices/{id}/history` | Beobachtete Versionen eines Preiseintrags |
| POST | `/v1/tracker/run` | Geschützt; Tracker im Hintergrund anstoßen |

Deployment: Migration `0006_receipts_tracker_history.sql` nach 0004/0005 auf
PostgreSQL/Supabase anwenden. SQLite erstellt die zusätzlichen Tabellen beim Start.
Systemd-Vorlagen stehen in `api/deploy/`; `@API_DIR@` vor Installation ersetzen.
Der Timer verweist auf den hier verwendeten Instanznamen des Sync-Dienstes.
Bons und Prospektoriginale persistent speichern. Betrieb:

```bash
systemctl status pricewatch-sync-e70d379d.timer
journalctl -u pricewatch-sync-e70d379d.service
cd api
uv run --env-file .env python -m pricewatch_api.cli track
```

OCR-Dokumentation: [PyMuPDF](https://pymupdf.readthedocs.io/en/latest/recipes-ocr.html),
[Tesseract](https://tesseract-ocr.github.io/tessdoc/Command-Line-Usage.html).
