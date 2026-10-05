"""Publish factual retailer audits, without treating archives as full price lists."""

import json
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/retailer-audit"

NOTES = {
    "aldi_nord": "Angebotskarten importiert; das Vollsortiment ist damit nicht erfasst.",
    "aldi_sued": (
        "Ausgewählte Angebotskarten importiert. Der allgemeine HTTP-Abruf meldet "
        "403 Access Denied; der vorhandene Händleradapter liefert Teilangebote."
    ),
    "penny": (
        "Regionale Angebote aus der öffentlichen Händlerschnittstelle für drei "
        "Märkte bei 85567 importiert. Keine vollständigen Regalpreise."
    ),
    "kaufland": (
        "Ausgewählte öffentliche Wochenangebote importiert; keine vollständige Sortimentsliste."
    ),
    "rewe": (
        "Grafing, Markt 461766: 312 bepreiste Artikel im gemeinsamen Browser "
        "erfasst. Der Serverabruf erhält 403/Menschprüfung. Dies sind "
        "Wochenangebote, kein vollständiger Onlineshop."
    ),
    "edeka": (
        "19 öffentlich sichtbare Preisvarianten im Browser importiert, darunter "
        "App-Angebote. Filialverfügbarkeit nicht bestätigt; direkte HTTP-Seiten "
        "teilweise 403."
    ),
    "globus": (
        "Alle 57 Seiten der öffentlichen Angebotsrubrik geprüft: 1.348 Artikel. "
        "Preise ohne bestätigte Markthalle; kein vollständiges Sortiment."
    ),
    "combi": (
        "Alle drei Seiten der Prospekt-Angebotsrubrik und 136 Produktdetailseiten "
        "importiert. Onlinepreise, keine zugesagten lokalen Regalpreise."
    ),
    "hit": (
        "22 öffentliche Angebotskarten importiert. Mehrere Varianten-EANs werden "
        "nicht als einzelne bestätigte EAN übernommen; Marktbezug unbestätigt."
    ),
    "norma": (
        "248 öffentlich lesbare Angebotskarten importiert. Teilweise ist nur ein "
        "Startdatum angegeben; ein Ablaufdatum wird nicht erfunden."
    ),
    "dm": (
        "Öffentliche Produktsuche mit expliziten EANs und Onlinepreisen "
        "importiert. Fortsetzung in begrenzten Batches; HTTP 429 führt zu "
        "Abkühlpause. Lokale Filialpreise nicht garantiert."
    ),
    "rossmann": (
        "312 Produktkarten über dreizehn Seiten im gemeinsamen Browser erfasst; "
        "weitere Seiten vorhanden. Serverabrufe erhalten Client Challenge/403. "
        "Onlineangebote, keine vollständige Preisdatei; Artikelnummern sind ohne "
        "zusätzlichen Beleg keine bestätigten EANs."
    ),
    "netto": (
        "Grafinger Markt 1399 ausgewählt und offiziellen 73-seitigen Prospekt "
        "heruntergeladen. Die geprüften Viewer-Hotspots liefern Bilddaten statt "
        "Produktpreise. PDF-Text allein ordnet Preise nicht zuverlässig Artikeln "
        "zu; daraus keine geratenen Preise importiert. Zusätzliche "
        "Marktguru-Angebote vorhanden."
    ),
    "lidl": (
        "Öffentlichen 73-seitigen Prospekt heruntergeladen und durchsuchbar "
        "gespeichert. Einzelne PDF-Preise noch nicht zuverlässig Produkten "
        "zugeordnet; zusätzliche Marktguru-Angebote und historische Belege "
        "vorhanden."
    ),
    "tegut": (
        "Öffentlichen Prospekt heruntergeladen; räumliche Preis-/Produktzuordnung "
        "noch nicht verifiziert. Zusätzliche historische Preisbelege vorhanden."
    ),
    "feneberg": (
        "Gefundener PDF-Download ist ein Speiseplan, keine Supermarkt-Preisliste. "
        "Historische Preisbelege vorhanden; aktuelle Angebotszuordnung noch nicht "
        "umgesetzt."
    ),
    "konsum_dresden": (
        "Offiziellen KW40-PDF-Prospekt heruntergeladen. Preise sind überwiegend "
        "grafisch; noch keine verifizierte Zuordnung zu Artikeln."
    ),
    "konsum_leipzig": (
        "Offiziellen KW40-PDF-Prospekt heruntergeladen. Keine eindeutig "
        "zuordenbaren Produktpreise im extrahierten Text; visueller Parser noch "
        "erforderlich."
    ),
    "wasgau": (
        "Aktueller Blätterprospekt über 1kcloud erreichbar. Keine strukturierten "
        "Product/Offer-Preise in den geprüften Seiten; Viewer-Parser noch nicht "
        "umgesetzt."
    ),
    "diska": (
        "Korrekte Prospektseite erreichbar; ältere Angebots-/Marktpfade liefern "
        "404. Kein strukturierter Preisexport gefunden; Prospekt-Parser noch "
        "nicht umgesetzt."
    ),
    "bio_company": (
        "Aktuelle Angebotsseite unter /neuigkeiten/angebote.html erreichbar; "
        "ältere Pfade liefern 404. Kein JSON-LD-Preisexport gefunden; eigener "
        "Angebotsparser noch nicht umgesetzt."
    ),
    "famila_nordwest": (
        "Korrekte Wochenangebotsseite erreichbar; alter /angebote/-Pfad liefert "
        "404. Kein eindeutiger strukturierter Preisexport gefunden; eigener "
        "Parser noch nicht umgesetzt."
    ),
    "netto_dog": (
        "Prospektseite erreichbar, aber keine einzelnen strukturierten "
        "Produktpreise im geprüften HTML. Viewer-Parser noch erforderlich; "
        "generische Netto-Belege werden dieser Kette nicht zugewiesen."
    ),
    "denns": (
        "Öffentliche Angebots-/Marktseiten geprüft. Keine eindeutigen "
        "Product/Offer-EUR-Preise extrahiert; regionaler Prospekt-Parser noch "
        "erforderlich. Historische Belege vorhanden."
    ),
    "markant": (
        "Öffentliche Seiten geprüft; Markt-/Prospektdarstellung liefert noch "
        "keinen übernommenen strukturierten Preisexport. Marktbezogener Parser "
        "erforderlich."
    ),
    "v_markt": (
        "Öffentliche Angebots-/Marktseiten geprüft; kein eindeutiger "
        "strukturierter Preisexport übernommen. Historische Preisbelege sind "
        "gesondert verfügbar."
    ),
    "famila_nordost": (
        "Öffentliche Angebots-/Marktseiten geprüft; kein eindeutiger "
        "strukturierter Preisexport übernommen. Generische famila-Belege bleiben "
        "ohne Zuordnung zur Teilkette."
    ),
}


def main():
    registry = json.loads((ROOT / "pricewatch_api/retailers.json").read_text())
    audits = {r["id"]: r for r in json.loads((DATA / "http-audit.json").read_text())}
    rows = []
    for retailer in registry:
        row = audits[retailer["id"]]
        attempts = row["attempts"]
        successes = [a for a in attempts if a.get("http_status") == 200]
        reason = NOTES.get(retailer["id"])
        if not reason:
            if successes:
                reason = (
                    "Offizielle Angebotsseite, alternative Markt-/Prospektseite und Startseite "
                    "geprüft. Kein eindeutig lesbarer Product/Offer-EUR-Preisexport gefunden. "
                    "Ein eigener Markt-/Prospektparser ist noch nicht umgesetzt; "
                    "keine Vollpreisliste heruntergeladen."
                )
            else:
                statuses = ", ".join(
                    str(a.get("http_status") or a.get("error", "Netzwerkfehler")) for a in attempts
                )
                reason = (
                    "Die geprüften offiziellen Angebots-, Alternativ- und Startseiten "
                    f"lieferten: {statuses}. Kein vollständiger Preisexport heruntergeladen; "
                    "einzelne Drittanbieter-/Archivbelege sind davon getrennt."
                )
        price_status = (
            "Teilpreise importiert"
            if retailer["id"]
            in {
                "aldi_nord",
                "aldi_sued",
                "penny",
                "kaufland",
                "rewe",
                "edeka",
                "globus",
                "combi",
                "hit",
                "norma",
                "dm",
                "rossmann",
            }
            else "Keine aktuellen Direktpreise importiert"
        )
        pdfs = row.get("downloaded_pdfs", [])
        if retailer["id"] == "netto":
            pdfs.append(json.loads((DATA / "netto-pdf-result.json").read_text()))
            attempts.append(
                {
                    "method": "shared_browser_store_selection_and_pdf",
                    "url": pdfs[-1]["viewer_url"],
                    "http_status": 200,
                    "reason": (
                        "Filiale 1399 Grafing bestätigt; PDF HTTP 200, 73 Seiten. Keine "
                        "verifizierte PDF-Preiszuordnung."
                    ),
                }
            )
        if retailer["id"] == "rossmann":
            attempts.append(
                {
                    "method": "shared_browser_product_cards",
                    "url": "https://www.rossmann.de/de/angebote/m/angebote",
                    "reason": "312 lesbare Produktkarten, dreizehn Seiten; Teilabruf.",
                }
            )
        if retailer["id"] == "rossmann":
            capture = json.loads((DATA / "rossmann-browser.json").read_text())
            count = len(capture["cards"])
            pages = len(capture["pages"])
            complete = capture.get("listing_complete", False)
            status = "Angebotsrubrik bis zur letzten Seite erfasst" if complete else "Teilabruf"
            reason = (
                f"{count} Online-Produktkarten über {pages} Seiten im Browser erfasst; {status}. "
                "Der HTTP-Abruf erhält Client Challenge/403. Nach Abbruch der T3-Verbindung "
                "konnte ein frischer Browser den öffentlichen Abruf fortsetzen. "
                "Keine vollständige Sortimentspreisliste; Filialpreise unbestätigt. "
                "URL-Artikelnummern werden ohne Beleg nicht als EAN übernommen."
            )
            attempts.append(
                {
                    "method": "fresh_browser_public_price_cards",
                    "url": "https://www.rossmann.de/de/angebote/m/angebote",
                    "reason": (
                        f"{count} Karten, {pages} Seiten; {status}. "
                        "Keine Konto-/Sitzungsdaten verwendet."
                    ),
                }
            )
        rows.append(
            {
                "id": retailer["id"],
                "name": retailer["name"],
                "full_price_list_downloaded": False,
                "price_status": price_status,
                "reason": reason,
                "attempts": attempts,
                "downloaded_pdfs": pdfs,
            }
        )
    result = {"checked_at": datetime.now(UTC).isoformat(), "retailers": rows}
    (ROOT / "pricewatch_api/retailer_coverage.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2)
    )
    report = [
        "# Händlerprüfung",
        "",
        f"Stand: {result['checked_at']}",
        "",
        "34 Händler/Teilketten geprüft. Keine vollständige Preisliste aller verkauften "
        "Produkte heruntergeladen. Teilangebote, Onlinepreise, historische Belege "
        "und reine Prospektdownloads sind unterschiedliche Ergebnisse.",
        "",
        "Die Website zeigt bei jedem Preis Quelle, Datum, Geltungsbereich und Bedingungen. "
        "Eine fehlende EAN wird nicht aus Artikelnummern oder Bildern erfunden.",
        "",
    ]
    for row in rows:
        report += [
            f"## {row['name']}",
            "",
            f"**{row['price_status']}; vollständige Preisliste: nein.** {row['reason']}",
            "",
        ]
        for a in row["attempts"]:
            report.append(
                f"- [{a['method']}]({a['url']}): "
                f"HTTP {a.get('http_status', 'nicht gemessen')} — {a.get('reason', '')}"
            )
        for pdf in row["downloaded_pdfs"]:
            report.append(
                f"- [PDF-Download]({pdf.get('url') or pdf.get('source_url')}): "
                f"{pdf.get('pages', '?')} Seiten; Produkt-/Preiszuordnung noch nicht bestätigt."
            )
        report.append("")
    (ROOT.parent / "docs").mkdir(exist_ok=True)
    (ROOT.parent / "docs/retailer-coverage.md").write_text("\n".join(report))
    print(f"Published {len(rows)} factual retailer audits")


if __name__ == "__main__":
    main()
