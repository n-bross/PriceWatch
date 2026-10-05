# Preisabdeckung je Händler – 04.10.2026

Prüfzeitpunkt: 2026-10-04T19:30:00.913893+02:00. Ausgewertet wurde die Datenbank der laufenden API, nicht die REWE-Testdatenbank. Die Importdienste liefen während der Prüfung weiter; spätere Zahlen können bereits höher liegen.

**Nein: Es sind nicht alle Produktpreise aller Händler eingespeist.** 35 registrierte Händler/Teilketten einschließlich dm, ROSSMANN und myTime wurden in der laufenden Datenbank geprüft. Für alle 35 wurde zusätzlich je eine registrierte offizielle Einstiegsseite erneut abgerufen. Ein HTTP-200-Ergebnis beweist weder korrekte Preise noch Vollständigkeit.

## Belastbare Prozentangaben und Grenzen

- **Combi: 99.51 % der aktuellen Sitemap-Produktseiten** (12.159/12.219) haben mindestens einen gespeicherten Direktpreis. 60 Seiten fehlen. Das ist Online-Quellenabdeckung, keine Zusage vollständiger Filialpreise.
- **dm: näherungsweise 41.35 %** (9.029/21.838) beim Vergleich gespeicherter Direktpreis-Artikel mit der aktuell gemeldeten Online-Kataloggröße. Historische IDs können inzwischen aus dem Sortiment genommen worden sein; keine exakt verifizierte Mengenüberschneidung.
- **REWE: 595/595 = 100 % nur für den getesteten Rabattfilter, Markt 461766, Abholung.** Diese 595 Datensätze stehen ausschließlich in der separaten Testdatenbank, nicht in der laufenden API. Die ungefilterte Suche meldet 10.000 Treffer (möglicherweise gedeckelt); damit sind 595 keinesfalls alle Produktpreise. Eine echte Vollsortimentsquote ist nicht belegt.
- **GLOBUS und myTime: 100 % der entdeckten Listenseiten bearbeitet**, nicht 100 % aller verkauften Produkte. Parserauslassungen, unbekannte Seiten und Filialunterschiede lassen sich aus dem Checkpoint nicht ausschließen.
- Für die übrigen Händler fehlt ein verifizierter Gesamtbestand im passenden Markt-/Kanalumfang. Eine Prozentzahl wäre erfunden. „Nicht bestimmbar“ bedeutet nicht automatisch 0 %.

## Alle registrierten Händler

„Direktartikel“ zählt unterschiedliche Artikel-IDs je direkter Quelle über alle gespeicherten Zeitstände; dies sind keine überall vergleichbaren, global deduplizierten Produkte. PENNY-Artikel werden über drei Filialen hinweg zusammengefasst. Bei mehreren Quellen bleiben Überschneidungen möglich.

„Heute belegt“ bedeutet am 04.10.2026 ausdrücklich datiert gültig oder heute beobachtet, ohne widersprechendes Gültigkeitsdatum. Es bestätigt keine Filialverfügbarkeit. 0 bedeutet fehlenden aktuellen Nachweis nach dieser strengen Regel, nicht zwangsläufig falsche Preise. App-/Mitgliedschaftspreise sind enthalten.

„Externe Belege“ sind rohe Drittanbieter-/Archivbeobachtungen; sie sind separat aufgeführt, weil sie weder aktuelle noch unterschiedliche Produkte beweisen.

| Händler | Direktartikel, alle Stände | Heute belegt | Externe Belege | Sortimentsquote |
|---|---:|---:|---:|---|
| ALDI Süd | 24 | 0 | 923 | nicht bestimmbar |
| ALDI Nord | 525 | 0 | 817 | nicht bestimmbar |
| Alnatura | 13 | 0 | 15 | nicht bestimmbar |
| Bio Company | 97 | 97 | 0 | nicht bestimmbar |
| CAP-Markt | 0 | 0 | 298 | nicht bestimmbar |
| Combi | 12.159 | 12.159 | 1 | 99,51 % Sitemap |
| Denns BioMarkt | 89 | 89 | 11 | nicht bestimmbar |
| diska | 0 | 0 | 0 | nicht bestimmbar |
| EDEKA | 41 | 0 | 4.181 | nicht bestimmbar |
| Feneberg | 0 | 0 | 55 | nicht bestimmbar |
| famila Nordost | 0 | 0 | 0 | nicht bestimmbar |
| famila Nordwest | 0 | 0 | 0 | nicht bestimmbar |
| GLOBUS | 58.985 | 58.985 | 4 | nicht bestimmbar |
| HIT | 45 | 0 | 155 | nicht bestimmbar |
| K+K Klaas & Kock | 0 | 0 | 0 | nicht bestimmbar |
| Kaufland | 76 | 71 | 2.508 | nicht bestimmbar |
| Lidl | 0 | 0 | 3.578 | nicht bestimmbar |
| Marktkauf | 0 | 0 | 8 | nicht bestimmbar |
| Mix Markt | 0 | 0 | 0 | nicht bestimmbar |
| Netto Marken-Discount | 0 | 0 | 2.775 | nicht bestimmbar |
| NORMA | 251 | 0 | 90 | nicht bestimmbar |
| PENNY | 647 | 0 | 962 | nicht bestimmbar |
| REWE | 318 | 312 | 38.651 | nicht bestimmbar |
| Netto mit Hund | 257 | 31 | 0 | nicht bestimmbar |
| tegut | 0 | 0 | 75 | nicht bestimmbar |
| V-Markt | 0 | 0 | 115 | nicht bestimmbar |
| WASGAU | 0 | 0 | 0 | nicht bestimmbar |
| nahkauf | 0 | 0 | 246 | nicht bestimmbar |
| Markant | 0 | 0 | 19 | nicht bestimmbar |
| Konsum Dresden | 0 | 0 | 2 | nicht bestimmbar |
| Konsum Leipzig | 0 | 0 | 0 | nicht bestimmbar |
| LPG BioMarkt | 0 | 0 | 2 | nicht bestimmbar |
| dm | 9.029 | 2.342 | 2.039 | ca. 41,35 % Onlineindex |
| ROSSMANN | 3.254 | 483 | 854 | nicht bestimmbar |
| myTime | 12.334 | 12.246 | 0 | nicht bestimmbar |

## Händlerdetails

- **ALDI Süd:** Angebotsauszug; derzeit keine nach dem strengen Stichtagskriterium aktuellen Direktpreise.
- **ALDI Nord:** Angebotsauszug; derzeit keine nach dem strengen Stichtagskriterium aktuellen Direktpreise.
- **Alnatura:** Teilangebote; gespeicherte Datierung am Stichtag abgelaufen oder zukünftig.
- **Bio Company:** Teilangebote, keine Sortimentsliste.
- **CAP-Markt:** Kein Direktpreisimport vorhanden; gegebenenfalls nur externe/historische Preisbeobachtungen.
- **Combi:** 12,159 von 12,219 aktuellen Sitemap-Produktseiten mit gespeichertem Preis; 60 fehlen, davon 57 Fehler im Checkpoint.
- **Denns BioMarkt:** Teilangebote, keine Sortimentsliste.
- **diska:** Kein Direktpreisimport vorhanden; gegebenenfalls nur externe/historische Preisbeobachtungen.
- **EDEKA:** Browser-Preisvarianten; Direktjob zuletzt HTTP 403. Die heute erneut geprüfte Registry-Seite lieferte HTTP 200; das belegt keinen erfolgreichen Import.
- **Feneberg:** Kein Direktpreisimport vorhanden; gegebenenfalls nur externe/historische Preisbeobachtungen.
- **famila Nordost:** Kein Direktpreisimport vorhanden; gegebenenfalls nur externe/historische Preisbeobachtungen.
- **famila Nordwest:** Kein Direktpreisimport vorhanden; gegebenenfalls nur externe/historische Preisbeobachtungen.
- **GLOBUS:** 2.913/2.913 entdeckte Seiten bearbeitet; 57.637 Artikel im abgeschlossenen Durchlauf. Kein unabhängiger Gesamtproduktzähler; zusätzliche ältere Angebotsimporte erklären 58.985 Quellartikel.
- **HIT:** Teilangebote; gespeicherte Datierung am Stichtag abgelaufen oder zukünftig.
- **K+K Klaas & Kock:** Kein Direktpreisimport vorhanden; gegebenenfalls nur externe/historische Preisbeobachtungen.
- **Kaufland:** Teilangebote, keine Sortimentsliste.
- **Lidl:** Kein Direktpreisimport vorhanden; gegebenenfalls nur externe/historische Preisbeobachtungen.
- **Marktkauf:** Kein Direktpreisimport vorhanden; gegebenenfalls nur externe/historische Preisbeobachtungen.
- **Mix Markt:** Kein Direktpreisimport vorhanden; gegebenenfalls nur externe/historische Preisbeobachtungen.
- **Netto Marken-Discount:** Kein Direktpreisimport vorhanden; gegebenenfalls nur externe/historische Preisbeobachtungen.
- **NORMA:** Teilangebote; häufig fehlt ein Enddatum. Null im strengen Aktualitätskriterium bedeutet nicht, dass alle Preise im Laden ungültig sind.
- **PENNY:** Angebotsartikel über drei Filialen nach Artikel-ID zusammengefasst; keine Vollsortimentspreise.
- **REWE:** 312 Browserartikel plus 6 manuelle Rechercheeinträge (quellenübergreifende Überschneidung möglich). Kein rewe_shop_pickup-Import in der laufenden Datenbank. 595 Abholangebote nur in separater Testdatenbank.
- **Netto mit Hund:** Teilangebote; getrennt von Netto Marken-Discount.
- **tegut:** Kein Direktpreisimport vorhanden; gegebenenfalls nur externe/historische Preisbeobachtungen.
- **V-Markt:** Kein Direktpreisimport vorhanden; gegebenenfalls nur externe/historische Preisbeobachtungen.
- **WASGAU:** Kein Direktpreisimport vorhanden; gegebenenfalls nur externe/historische Preisbeobachtungen.
- **nahkauf:** Kein Direktpreisimport vorhanden; gegebenenfalls nur externe/historische Preisbeobachtungen.
- **Markant:** Kein Direktpreisimport vorhanden; gegebenenfalls nur externe/historische Preisbeobachtungen.
- **Konsum Dresden:** Kein Direktpreisimport vorhanden; gegebenenfalls nur externe/historische Preisbeobachtungen.
- **Konsum Leipzig:** Kein Direktpreisimport vorhanden; gegebenenfalls nur externe/historische Preisbeobachtungen.
- **LPG BioMarkt:** Kein Direktpreisimport vorhanden; gegebenenfalls nur externe/historische Preisbeobachtungen.
- **dm:** 9,029 Quellartikel mit gespeichertem Preis / 21,838 aktuell gemeldete Suchtreffer = ca. 41.35 %. Näherung, da die Mitgliedschaft aller alten IDs im heutigen Katalog nicht vollständig neu geprüft wurde.
- **ROSSMANN:** Online-Teilpreise; Angebote und Lebensmittelrubrik. Angebotscrawler nach 21 Seiten blockiert; keine verifizierte Gesamtzahl.
- **myTime:** 256/256 Listenseiten im letzten Durchlauf bearbeitet, 12.246 Artikel im Checkpoint. Kein unabhängiger Gesamtproduktzähler. Registry-Einstiegslink HTTP 404; kein Beleg für den Ausfall des gesamten Importers.

## Frische HTTP-Prüfung der registrierten Einstiegsseiten

Die Prüfung ist ein begrenzter Erreichbarkeitstest, kein vollständiger Produktcrawl. Veraltete Registry-Links können trotz funktionierender spezieller Importquelle scheitern.

| Händler | Ergebnis | Geprüfte Quelle |
|---|---|---|
| ALDI Süd | 200 | [Händlerseite](https://www.aldi-sued.de/angebote) |
| ALDI Nord | 200 | [Händlerseite](https://www.aldi-nord.de/angebote.html) |
| Alnatura | 200 | [Händlerseite](https://www.alnatura.de/maerkte/angebote-vorschau) |
| Bio Company | 200 | [Händlerseite](https://www.biocompany.de/neuigkeiten/angebote.html) |
| CAP-Markt | 404 | [Händlerseite](https://cap-markt.de/angebote/) |
| Combi | 200 | [Händlerseite](https://www.combi.de/prospekt-angebote_220012750.html) |
| Denns BioMarkt | 200 | [Händlerseite](https://www.biomarkt.de/angebote) |
| diska | 200 | [Händlerseite](https://diska.de/prospekt/) |
| EDEKA | 200 | [Händlerseite](https://www.edeka.de/angebote/) |
| Feneberg | 200 | [Händlerseite](https://www.feneberg.de/angebote/) |
| famila Nordost | 200 | [Händlerseite](https://www.famila-nordost.de/angebote/) |
| famila Nordwest | 200 | [Händlerseite](https://www.famila-nordwest.de/aktuelles/wochenangebote) |
| GLOBUS | 200 | [Händlerseite](https://produkte.globus.de/angebote-der-woche/) |
| HIT | 200 | [Händlerseite](https://www.hit.de/angebote-coupons) |
| K+K Klaas & Kock | 200 | [Händlerseite](https://www.klaas-und-kock.de/angebote/) |
| Kaufland | 200 | [Händlerseite](https://filiale.kaufland.de/angebote.html) |
| Lidl | 200 | [Händlerseite](https://www.lidl.de/c/online-prospekte/s10005610/) |
| Marktkauf | 403 / Sperrhinweis | [Händlerseite](https://www.marktkauf.de/angebote/) |
| Mix Markt | 200 | [Händlerseite](https://www.mixmarkt.eu/de/germany/angebote/) |
| Netto Marken-Discount | 403 / Sperrhinweis | [Händlerseite](https://www.netto-online.de/ueber-netto/Online-Prospekte.chtm/1013) |
| NORMA | 200 | [Händlerseite](https://www.norma-online.de/de/angebote/) |
| PENNY | 200 | [Händlerseite](https://www.penny.de/angebote) |
| REWE | 403 | [Händlerseite](https://www.rewe.de/angebote/grafing/461766/rewe-leonhardstr-5-a/) |
| Netto mit Hund | 200 | [Händlerseite](https://netto.de/prospekte/) |
| tegut | 200 | [Händlerseite](https://mittelhessen.tegut.com/) |
| V-Markt | 200 | [Händlerseite](https://www.v-markt.de/angebote/) |
| WASGAU | 200 | [Händlerseite](https://wasgau-dlog.1kcloud.com/ep1rP1V0/) |
| nahkauf | 404 | [Händlerseite](https://www.nahkauf.de/angebote) |
| Markant | ReadTimeout | [Händlerseite](https://www.markant-online.de/angebote/) |
| Konsum Dresden | 200 | [Händlerseite](https://www.konsum.de/angebote/) |
| Konsum Leipzig | 404 | [Händlerseite](https://www.konsum-leipzig.de/angebote/) |
| LPG BioMarkt | 200 | [Händlerseite](https://www.lpg-biomarkt.de/angebote/) |
| dm | 200 | [Händlerseite](https://www.dm.de/ernaehrung) |
| ROSSMANN | 403 | [Händlerseite](https://www.rossmann.de/de/angebote) |
| myTime | 404 | [Händlerseite](https://www.mytime.de/lebensmittel_10000000.html) |

## Quellen für Nenner und Belege

- [combi: Aktuelle Sitemap-Produktseiten mit mindestens einem gespeicherten Direktpreis](https://www.combi.de/sitemaps/combi/sitemap.produkte.xml)
- [dm: Gespeicherte Direktpreis-Artikel / gemeldete aktuelle Onlinesuchtreffer (Näherung)](https://product-search.services.dmtech.com/de/search?query=&pageSize=1&currentPage=0)
- [rewe: Nur separate Testdatenbank: erfasste rabattierte Abholartikel für Markt 461766](https://www.rewe.de/shop/api/products?serviceTypes=PICKUP&marketId=461766&attribute=discounted)
- [REWE ungefilterte Abholsuche](https://www.rewe.de/shop/api/products?serviceTypes=PICKUP&marketId=461766)
- Read-only SQLite-Abfragen auf `external_price_observations` und `price_catalog` der laufenden API; keine Beleginhalte gelesen oder verändert.
- Laufende API: `/opt/t3code/worktrees/PriceWatch/t3code-e70d379d/api/pricewatch.db`.
- Checkpoints: `data/expansion/globus-bulk.json`, `combi-bulk.json`, `mytime-progress.json`, `data/catalog/dm-progress.json`, `data/rossmann-recurring/state.json`.
- [Maschinenlesbare Zusammenfassung](price-coverage-2026-10-04.json).
