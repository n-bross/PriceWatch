# PriceWatch — Setup (Phase 0)

Anleitung für das Einrichten auf dem Mac. Diese Schritte kann Claude Code auf dem Mac
weitgehend selbst ausführen — die mit **[Mensch]** markierten Schritte brauchen einen
Browser-Login und müssen manuell gemacht werden.

## Was Phase 0 ist

Einkaufslisten-App (AnyList-Stil) mit Supabase-Backend: E-Mail-OTP-Login, Listen +
Items mit Realtime-Sync zwischen Geräten. Dieses Dokument beschreibt das ursprüngliche
iOS-Setup; den inzwischen erweiterten Funktionsumfang nennt der Implementierungsstand unten.

## Schritte

### 1. [Mensch] Supabase-Projekt anlegen

1. Auf https://supabase.com einloggen/registrieren, neues Projekt anlegen
   (Region: EU, z.B. Frankfurt).
2. Unter *Project Settings → API* kopieren:
   - **Project URL** (`https://<ref>.supabase.co`)
   - **anon public key**

### 2. Datenbank-Migration einspielen

Entweder per Supabase CLI:

```bash
brew install supabase/tap/supabase
supabase login          # [Mensch] öffnet Browser
supabase link --project-ref <ref>
supabase db push
```

…oder einfacher: Inhalt von `supabase/migrations/0001_init.sql` im Supabase-Dashboard
unter *SQL Editor* einfügen und ausführen.

Danach unter *Authentication → Providers → Email* prüfen, dass Email-Login aktiv ist
(OTP/Magic-Link ist Standard).

### 3. Xcode-Projekt konfigurieren

1. **SPM-Package hinzufügen:** `https://github.com/supabase/supabase-swift`,
   Produkt `Supabase`, zum Target `PriceWatch`.
   (In Xcode: File → Add Package Dependencies. Per CLI/pbxproj-Edit auch möglich.)
2. **Neue Dateien einbinden:** Die Ordner `PriceWatch/Core`, `PriceWatch/Models`,
   `PriceWatch/Features` müssen ins Xcode-Projekt aufgenommen werden
   (Add Files to "PriceWatch"…, Target-Häkchen bei PriceWatch). Das Projekt nutzt
   das klassische pbxproj-Format (objectVersion 56), neue Dateien werden also
   NICHT automatisch aufgenommen. Alternative: Gruppen auf
   "File System Synchronized" umstellen oder pbxproj direkt editieren.
3. **Konfiguration:**
   - `Config/Supabase.xcconfig.example` → nach `Config/Supabase.xcconfig` kopieren,
     Werte aus Schritt 1 eintragen (Datei ist gitignored).
   - Im Projekt (Project → Info → Configurations) `Supabase.xcconfig` für Debug
     und Release zuweisen.
   - Im Target unter Info zwei Info.plist-Einträge anlegen:
     `SUPABASE_URL = $(SUPABASE_URL)` und `SUPABASE_ANON_KEY = $(SUPABASE_ANON_KEY)`.

### 4. Bauen und testen

```bash
xcodebuild -project PriceWatch.xcodeproj -scheme PriceWatch \
  -destination 'platform=iOS Simulator,name=iPhone 15' build
```

Der aktuelle iOS-Build muss auf einem Mac mit Xcode verifiziert werden; die
Python-/JavaScript-CI prüft ihn nicht. Bei Build-Fehlern insbesondere die zur
eingebundenen supabase-swift-Version passenden APIs prüfen (Realtime
`postgresChange`, `signInWithOTP`, `AnyJSON`).

**Fertig-Kriterium (manuell im Simulator durchspielen):**

1. App starten → E-Mail eingeben → Code aus der Mail eintippen → eingeloggt.
2. Liste erstellen, Item hinzufügen, Item abhaken.
3. App beenden und neu starten → Stand ist noch da (kommt aus Supabase).
4. Zweiten Simulator mit demselben Account starten → Änderungen erscheinen live
   ohne Refresh (Realtime).

## Implementierungsstand und nächste Schritte

### Gemeinsamer Preisvergleich auf iOS und im Browser

Die iOS-App hat zusätzlich den Tab **Preise**, der dieselbe `/v1/compare`-API wie
die Browseroberfläche abfragt. Produktname/EAN, PLZ und Mitgliedschaftsfilter
stehen zur Verfügung. Herkunft, Datum, Abhol-/Online-/Filialkontext und
Bonusguthaben werden getrennt angezeigt; Ergebnisse lassen sich seitenweise laden.

Standardserver: `https://vps.tail179a46.ts.net:9450`. Auf dem iPhone muss Tailscale
mit dem passenden Tailnet verbunden sein. Die Adresse lässt sich in den
App-Einstellungen ändern oder beim Build über `PRICEWATCH_API_URL` in
`Config/Supabase.xcconfig` vorbelegen. Für diese Leseabfragen wird kein
Import- oder Datenbanktoken an die App gegeben.

Die neuen REWE-Abholpreise erscheinen im Tab **Preise**. Die ältere Supabase-
Angebotstabelle speist weiterhin den separaten Tab „Angebote“ und die bisherigen
Angebotszuordnungen der Einkaufslisten.

Für die neue iOS-Anbindung sind Decoder-/Anfragetests in `PriceWatchTests` ergänzt.
Sie müssen mit Xcode auf macOS ausgeführt werden; auf dem Entwicklungsserver
stehen kein SwiftUI-SDK und kein iOS-Simulator zur Verfügung.

Die ursprüngliche Phasenplanung wurde teilweise durch die Preis-API ersetzt:

- **iOS:** Listen, Anmeldung, Sync, Angebotsanzeige und erste Angebotszuordnung sind
  implementiert. Die oben beschriebene Abnahme mit Xcode und zwei Geräten bleibt
  separat nachzuweisen.
- **Web:** Die Vergleichsoberfläche wird von der FastAPI-Anwendung ausgeliefert
  (`/` und `/compare`). Eine synchronisierte Web-Einkaufsliste ist darin nicht enthalten.
- **Importe:** Händleradapter, wiederkehrende Jobs, Produktkatalog und marktbezogener
  REWE-Abholpreisimport liegen unter `/api`. Bereitstellung und aktuelle Erreichbarkeit
  einer Quelle sind getrennt vom Implementierungsstand zu prüfen.
- **Prospekte:** PDF-Download und Textsuche existieren. Eine vollständige Vision-/OCR-
  Extraktion von Produktpreisen für bislang nicht abgedeckte Händler bleibt offen.

Aktuelle Anleitungen: [Preis-API](api/README.md),
[REWE-Import](api/docs/rewe-recurring.md) und
[historischer Betriebsstand](api/docs/continuation-status.md).
