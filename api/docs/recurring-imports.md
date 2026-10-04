# Wiederkehrende Preisimporte

Die erweiterten Importe laufen als systemd-Dienste unabhängig von T3 oder einem
Agenten. Gemini wird für die Entwicklung verwendet, nicht bei jedem Preisabruf.
Die API startet selbst keine Hintergrundimporte.

| Quelle | Ausführung | Arbeit pro Lauf |
| --- | --- | --- |
| GLOBUS Sortiment | alle 15 Minuten | bis 100 Seiten, 2 parallele Abrufe |
| Combi Sortiment | alle 15 Minuten | bis 200 Produktseiten, 2 parallele Abrufe |
| myTime | alle 15 Minuten | bis 50 Listenseiten, anschließend bis 100 Produktdetails |
| Denns, BIO COMPANY, Alnatura, Netto mit Hund | alle 6 Stunden | öffentliche Angebotsseiten, bedingte HTTP-Abrufe |
| GLOBUS/Combi Wochenangebote, HIT, NORMA | täglich ab 06:40 Uhr | bestehender Händlerseiten-Import |
| dm | alle 30 Minuten | bestehender begrenzter Import mit Quellensperrzeiten |
| ALDI/PENNY/Quellentracker | alle 15 Minuten | bestehender Tracker |
| Open Food Facts | sonntags | Produktstammdaten, keine Händlerpreise |

Die 15 Minuten sind der Takt für kleine Arbeitspakete, keine Zusage, dass jeder
Preis alle 15 Minuten neu geprüft wird. Unfertige Sortimente werden fortgesetzt. Bei GLOBUS/Combi werden Seiten nach
drei Fehlern für diesen Durchlauf zurückgestellt und beim nächsten Durchlauf
erneut entdeckt; die Fehler bleiben im Checkpoint sichtbar.
Nach Abschluss pausiert der Sortimentsimport standardmäßig 24 Stunden vor dem
nächsten vollständigen Durchlauf. Die tatsächlich erreichbare Frische hängt von
Sortimentsgröße, Antwortzeiten und Sperrzeiten der Händler ab.

Checkpoints und Prozesssperren verhindern Neustarts bei Seite 1 und parallele
Durchläufe desselben Imports. HTTP-429-Antworten führen zu einer Pause. Bestätigte
myTime-EAN-Zuordnungen bleiben für weitere Listendurchläufe erhalten; dadurch
müssen bekannte Produktdetails nicht jedes Mal neu abgerufen werden.

Die vier Angebotsquellen senden ETag/Last-Modified-Prüfungen, soweit vom Händler
unterstützt. Nur eine erfolgreiche Antwort (einschließlich HTTP 304) bestätigt
Daten erneut. Fehler erzeugen keine neuen Preisbeobachtungen. Nicht jeder Händler
unterstützt bedingte Anfragen; dort bleibt ein regulärer Download notwendig.
Identische Beobachtungen werden durch die bestehenden Datenbank-IDs dedupliziert;
ein erfolgreich neu beobachteter Preis an einem späteren Tag bleibt als Historie.

REWE, EDEKA und ROSSMANN benötigen weiterhin einen erneuten Browserabruf.
Der Zeitplan macht diese Quellen nicht automatisch aktuell. Onlinepreise und
regionale Angebote bleiben entsprechend gekennzeichnet.

## Installation auf diesem Server

Aus dem Repository:

```bash
sudo bash api/deploy/install-recurring.sh
```

Voraussetzungen: vorhandene `api/.venv`, installierte API, initialisierte Datenbank
und private `api/.env` mit `DATABASE_URL`. Der Installer aktiviert vier Timer,
ohne die bestehenden Timer zu ersetzen. Vor Entfernen dieses Worktrees die
Dienste umstellen oder deaktivieren. Die Vorlagen nutzen den Instanzsuffix
`e70d379d`; für eine weitere Installation einen anderen Suffix wählen.

## Kontrolle

```bash
systemctl list-timers --all 'pricewatch-*'
systemctl status pricewatch-mytime-e70d379d.service
journalctl -u pricewatch-mytime-e70d379d.service -n 30 --no-pager
journalctl -u pricewatch-recovered-offers-e70d379d.service -n 30 --no-pager
```

Fortschritt liegt in `api/data/expansion/`: `globus-bulk.json`,
`combi-bulk.json`, `mytime-progress.json` und `recovered-sources-status.json`.
Die Dateien zeigen bearbeitete/offene Seiten, Abschluss beziehungsweise Fehler
und Sperrzeiten. Ein erfolgreich beendeter Dienst allein bedeutet nicht, dass
das gesamte Sortiment schon eingelesen wurde; ein begrenzter Lauf kann regulär
mit offenem Fortschritt oder einer Quellensperrzeit enden.

Manuell denselben Dienst starten (systemd verhindert doppelte Dienststarts):

```bash
sudo systemctl start pricewatch-mytime-e70d379d.service
```

`--reset` ist nur für einen bewusst erzwungenen Neuanfang vorgesehen; die Timer
verwenden es nicht. Für normale Aktualisierungen bleibt der Fortschritt erhalten.

## Verifikation am 4. Oktober 2026

Alle vier neuen Timer wurden auf diesem Server aktiviert. Zwei echte Läufe der
15 Angebotsseiten endeten ohne Abruffehler; der zweite Lauf verwendete bei neun
Seiten HTTP 304. GLOBUS, Combi und myTime haben ihre ersten begrenzten Läufe
begonnen und speichern neue Preise mit Checkpoints. Die großen Sortimente waren
zum Prüfzeitpunkt noch nicht vollständig durchlaufen.

31 gezielte Tests für Parser, Wiederholung, HTTP-Cache, Sperren, Fehlerfälle und
Datumsbehandlung bestanden. Die zuvor ausgeführte gesamte Testsuite bestand mit
122 Tests und einem mangels Testdatenbank übersprungenen PostgreSQL-Test.

## Importstatus und Abfrageindex

`GET /v1/import-status` und „Preisimporte und Datenstand“ auf der Vergleichsseite
zeigen gespeicherten Durchlauffortschritt, Fehler/Pausen und das letzte beobachtete
Preisdatum getrennt. Beobachtungszahlen enthalten Historie und regionale Varianten;
sie sind keine Anzahl aktuell verfügbarer Produkte. Ein Checkpoint beweist weder
einen laufenden Prozess noch einen aktivierten Timer.

Für Quelle/Anzahl/letztes Preisdatum nutzt die Datenbank den zusammengesetzten Index
`external_prices_source_date (source, price_date)`. Damit entfällt das Lesen der
großen Beobachtungsdatensätze samt JSON-Nutzdaten für diese Aggregation. SQLite
rüstet ihn bei `Database.initialize()` auch auf bestehenden Datenbanken nach.
PostgreSQL/Supabase benötigt Migration `0009_observation_status_index.sql`.

Live-Messung am 4. Oktober 2026: vor dem Index HTTP-Abbruch nach 25 Sekunden;
nach Index und API-Neustart rund 0,9 Sekunden für den Endpunkt. Die reine
SQL-Aggregation dauerte 0,10 Sekunden und nutzt laut SQLite-Abfrageplan den
abdeckenden Index. Werte hängen von Datenmenge und Serverlast ab.
