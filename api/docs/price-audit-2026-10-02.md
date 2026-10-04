# Zufällige Preisstichprobe – 02.10.2026

Prüfung der laufenden API über Tailscale, PLZ 85567. Zwei zufällig ausgewählte aktuelle Standardangebote pro Händler aus den fünf Händlern mit gespeicherten Produktpreisen. Auswahl vor dem Quellenvergleich, reproduzierbarer Python-RNG-Seed `202610021`; Händlerreihenfolge ebenfalls gemischt. Penny auf Filiale 565668 (Glonn) begrenzt, um Dreifachzählung derselben Produkte über drei Filialen zu vermeiden. App-/Card-Preise waren in dieser Stichprobe ausgeschlossen.

Die Händlerquellen wurden erneut abgerufen. Penny zusätzlich über konkrete Produktseiten mit sichtbarem Produktpreis; ALDI Nord über frische eingebettete Händlerdaten, Kaufland über HTML und eingebettete Daten, ALDI Süd über Produktseiten und Wochenangebotsübersicht. REWE Grafing über den Web-Rechercheabruf der offiziellen Marktseite, weil direkte Serverabrufe blockiert werden. Es wurde nicht nur derselbe Importparser erneut ausgeführt.

| Händler | Produkt | API vorher | Händler beim frischen Abruf / API nachher | Bezug | Quelle |
| --- | --- | --- | --- | --- | --- |
| penny | OREO Kekse | 1,29 € | 1,29 € | je 154 g | [Händler](https://www.penny.de/angebote/suessigkeiten-und-snacks/oreo-kekse) |
| penny | Ginseng-Bonsai | 9,99 € | 9,99 € | je Stück | [Händler](https://www.penny.de/angebote/pflanzen-mo-sa/ginseng-bonsai) |
| kaufland | Dtsch./span. Eisbergsalat | 0,69 € | 0,65 € | je Stück | [Händler](https://filiale.kaufland.de/angebote.html) |
| kaufland | BARILLA Classic Pasta | 0,75 € | 0,75 € | je 500-g-Packg. | [Händler](https://filiale.kaufland.de/angebote.html) |
| aldi_sued | BIO NATURLAND Bio Naturland Hokkaido, lose | 0,99 € | 0,99 € | 1 kg (lose; nach Gewicht) | [Händler](https://www.aldi-sued.de/produkt/bio-naturland-bio-naturland-hokkaido-lose-000000000000523858) |
| aldi_sued | Gurke, Stück | 0,49 € | 0,49 € | 1 Stück | [Händler](https://www.aldi-sued.de/produkt/no-brand-gurke-stueck-000000000000229921) |
| rewe | Wagner Big City Salami | 1,99 € | 1,99 € | 415 g | [Händler](https://www.rewe.de/marktseite/grafing/461766/rewe-markt-leonhardstr-5-a/) |
| rewe | Wagner Die Backfrische Mozzarella | 1,99 € | 1,99 € | 350 g | [Händler](https://www.rewe.de/marktseite/grafing/461766/rewe-markt-leonhardstr-5-a/) |
| aldi_nord | BABYBEL Mini | 2,89 € | 2,89 € | 10x20-g-Netz | [Händler](https://www.aldi-nord.de/produkt/mini-1010817.html) |
| aldi_nord | HAVANA CLUB Especial | 10,99 € | 10,99 € | 0,7-L-Flasche | [Händler](https://www.aldi-nord.de/produkt/especial-1009246.html) |

## Befunde und Korrekturen

9/10 ursprüngliche Preisbeträge stimmen mit den frisch abgerufenen Händlerangaben überein. Kaufland-Eisbergsalat: API zuerst 69 Cent; direkte aktuelle Website lieferte 65 Cent bei identischer Angebots-ID ART.176395_KAV.3669723. Der Web-Rechercheabruf derselben URL zeigte weiterhin 69 Cent. Deshalb ist die Ursache (Änderung seit dem Morgen, Cache oder unterschiedliche Seitenauslieferung) nicht abschließend bewiesen. Der Kaufland-Snapshot wurde erneut synchronisiert und die API liefert nun 65 Cent. Keine automatische Zusage der Gültigkeit in allen Kaufland-Filialen.

ALDI Süd Hokkaido: Betrag 99 Cent war richtig, der Preis gilt aber pro kg. comparisonDisplay war null; perUnitDisplay enthielt 1 kg und isRandomWeight war true. Der Parser ignorierte diese Preisbasis. Regressionstest zunächst fehlgeschlagen, Parser korrigiert: package_label=1 kg (lose; nach Gewicht), unit_price_cents=99, unit_price_unit=kg und Gewichtshinweis. Auch lose Mandarinen werden damit korrekt erfasst. Gurke ohne sellingSize erhält jetzt den expliziten Stückbezug aus quantityUnit=ea.

Gültigkeit: ALDI Süd 28.09.–02.10.; ALDI Nord und Penny 28.09.–03.10.; Kaufland 01.10.–07.10.; REWE in der API 28.09.–03.10. Die REWE-Marktseite bezeichnet die Prospektwoche als 28.09.–04.10.; das API-Enddatum ist auf den Samstag begrenzt, und der Markt meldet am 03.10. geschlossen. REWE Bonus 20 Cent bei den geprüften Pizzen ist zukünftiges Guthaben und wurde korrekt nicht vom Kassenpreis 1,99 € abgezogen.

Nach Aktualisierung 10/10 geprüfte Preisbeträge passend zum jeweiligen hier frisch abgerufenen Händlerdatensatz. Stichprobe bestätigt keine vollständige Abdeckung, Lagerbestände oder Preisgleichheit zwischen Filialen. Lidl-/tegut-PDFs enthalten bisher ungeprüften Suchtext, keine Produktpreisdatensätze; sie wurden deshalb nicht als verifizierte Preise in diese Stichprobe aufgenommen.

Zeitpunkt des Ergebnisprotokolls: 2026-10-02T11:18:50.742869+00:00. Vorher-/Nachher-API-Daten: [JSON](price-audit-2026-10-02.json).
