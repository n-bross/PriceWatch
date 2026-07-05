# PriceWatch — Setup (Phase 0)

Anleitung für das Einrichten auf dem Mac. Diese Schritte kann Claude Code auf dem Mac
weitgehend selbst ausführen — die mit **[Mensch]** markierten Schritte brauchen einen
Browser-Login und müssen manuell gemacht werden.

## Was Phase 0 ist

Einkaufslisten-App (AnyList-Stil) mit Supabase-Backend: E-Mail-OTP-Login, Listen +
Items mit Realtime-Sync zwischen Geräten. Angebots-Features (Supermarkt-Prospekte)
folgen in späteren Phasen — siehe Roadmap unten.

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

Build-Fehler sind hier erwartbar (der Swift-Code wurde auf einem Linux-Server ohne
Xcode geschrieben und noch nie kompiliert) — insbesondere können sich die
supabase-swift-APIs (Realtime `postgresChange`, `signInWithOTP`, `AnyJSON`) je nach
SDK-Version leicht unterscheiden. Fehler direkt fixen.

**Fertig-Kriterium (manuell im Simulator durchspielen):**

1. App starten → E-Mail eingeben → Code aus der Mail eintippen → eingeloggt.
2. Liste erstellen, Item hinzufügen, Item abhaken.
3. App beenden und neu starten → Stand ist noch da (kommt aus Supabase).
4. Zweiten Simulator mit demselben Account starten → Änderungen erscheinen live
   ohne Refresh (Realtime).

## Roadmap (Kontext)

- **Phase 0 (dieses Setup):** iOS-Grundgerüst + Supabase-Sync ✓ Code geschrieben
- **Phase 1:** Web-App (Next.js + supabase-js) gegen dasselbe Backend → `/web`
- **Phase 2:** Angebots-Ingestion (Python-Worker, Marktguru-Quelle) + Browse-Screen → `/worker`
- **Phase 3:** Fuzzy-Matching Listen-Items ↔ Angebote (pg_trgm), "im Angebot"-Badges
- **Phase 4:** PDF-Prospekt-Pipeline mit Vision-LLM für nicht abgedeckte Händler
