# Produktive Preiserweiterung – 04.10.2026

Stand: 2026-10-04T21:34:29.413480+00:00

- **REWE:** 14.702 unterschiedliche Abholartikel für Markt 461766 / PLZ 85567 in der laufenden Datenbank. 16 entdeckte Sortimentskategorien und 381 Seiten verarbeitet. 15.297 Beobachtungen einschließlich der überlappenden 595 Rabattangebote; diese beiden Zahlen dürfen nicht addiert als Produktzahl ausgegeben werden.
- **dm:** 9397 → 9732 unterschiedliche Direktpreis-Artikel während der laufenden Importe. HTTP-429-Pausen werden weiterhin eingehalten.
- **Marktguru:** zusätzlicher Angebotsabruf ausgeführt; 460 zusätzliche Beobachtungen im Datenbestand. Dies ist keine Zahl unterschiedlicher aktueller Produkte.
- **Combi:** die meisten verbleibenden Lücken sind 57 vom Händler entfernte Produktseiten (HTTP 410), keine noch nicht gestarteten Abrufe.
- **EDEKA:** erneuter Importversuch weiterhin HTTP 403. Bestehende Daten bleiben erhalten.

## Nutzung und Betrieb

- [Laufender Browser-Preisvergleich](https://vps.tail179a46.ts.net:9450/): neue REWE-Preise über `/v1/compare` mit Markt, PLZ und Abholkontext geprüft.
- Der neue iOS-Tab **Preise** verwendet denselben Endpunkt. App-Einstellungen enthalten die HTTPS-Serveradresse; für den Standardserver muss Tailscale verbunden sein. Die bisherigen Supabase-Angebote bleiben separat.
- `pricewatch-rewe-catalog.timer` ist aktiviert. Er startet alle 15 Minuten begrenzte Arbeitsläufe; abgeschlossene Durchläufe pausieren mindestens 24 Stunden. Marktbezogene Checkpoints und Prozesssperren verhindern parallele Läufe.
- `/v1/import-status` zeigt „REWE Abholsortiment“, Artikel- und Seitenfortschritt. Der Status bestätigt den gespeicherten Durchlauf, nicht eine lückenlose Abdeckung aller Märkte.
- API und neuer Importdienst verwenden `/opt/pricewatch/releases/20261004-rewe-catalog`. Der bestehende Datenpfad bleibt `/opt/t3code/worktrees/PriceWatch/t3code-e70d379d/api`; vor dem Entfernen dieses Daten-Worktrees muss er separat migriert werden.

## Prüfung

- 39 gezielte Backend-Tests für REWE-Abruf, Wiederaufnahme, Preisvergleich und Statusanzeige erfolgreich. Ruff ohne Befund.
- iOS-Decoder-/Anfragetests ergänzt; Info.plist und Projekt-Dateiverweise geprüft. **Kein iOS-Build und kein Simulatorlauf möglich**, da diese Umgebung kein macOS/Xcode bietet.
- Eine unnötige Vollsuche in der Detailabfrage durch einen Regressionstest nachgewiesen und auf ausgewählte EANs/Artikel-IDs begrenzt. Identische angezeigte Belege werden zusammengefasst, abweichende Beträge und Kontexte bleiben erhalten.
- Lokale Messung der breiten Suche „Milch“ nach der Optimierung: rund 3,5 Sekunden; die Detailabfrage selbst rund 0,002 Sekunden. Laufzeit hängt von Serverlast und Datenmenge ab.
- Abschließender HTTP-Aufruf derselben breiten Suche am laufenden Server: 9,23 Sekunden innerhalb des 10-Sekunden-Testlimits. Die Suche bleibt unter Serverlast spürbar langsam.

[Maschinenlesbare Importdifferenz](price-expansion-2026-10-04.json).
