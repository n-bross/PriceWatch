# PriceWatch

iOS-Einkaufslisten-App mit Supabase und einer API für Supermarktpreise/Angebote.

- [Preis-API: Start, Endpunkte und Datenabdeckung](api/README.md)
- [Händlerprüfung: Ergebnisse und Abrufprobleme pro Supermarkt](docs/retailer-coverage.md)
- [iOS-/Supabase-Setup](SETUP.md)
- [Produktive Preiserweiterung und iOS-Preisvergleich](api/docs/price-expansion-2026-10-04.md)

Die Vergleichswebsite liegt unter `/` und `/compare`. Suche nach Produktname oder EAN,
PLZ- und Händlerfilter sowie getrennte Anzeige historischer und App-Preise sind verfügbar.
Die Händlerabdeckung nennt die tatsächlich geprüften Quellen und Prospektdownloads.
Eine vollständige Preisliste sämtlicher deutscher Supermärkte liegt nicht vor.

Die Vergleichs-API nutzt `GET /v1/compare?q=Lavazza&postal_code=85567` oder
`GET /v1/compare?ean=4008400401829&postal_code=85567`. Weitere Parameter sind
`retailer`, `include_history`, `include_membership`, `limit` und `offset`.
`GET /v1/coverage` liefert die Händlerprüfung. Preise stehen in Eurocent;
Quellen, Erfassungsdatum, Gültigkeit und Geltungsbereich gehören zu jedem Preis.
