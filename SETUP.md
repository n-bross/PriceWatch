# PriceWatch — Technisches Setup-Handbuch

Kurzanleitung zur lokalen Einrichtung von **PriceWatch** mit Xcode und einem eigenen Supabase-Projekt.

## 1. Supabase-Projekt erstellen

1. Erstelle auf [supabase.com](https://supabase.com) ein neues Projekt (z. B. Region `eu-central-1` / Frankfurt).
2. Kopiere unter **Project Settings → API**:
   - **Project URL** (`https://<ref>.supabase.co`)
   - **anon public key**

## 2. Datenbank-Migrationen ausführen

Entweder über die Supabase CLI:

```bash
brew install supabase/tap/supabase
supabase login
supabase link --project-ref <ref>
supabase db push
```

Oder manuell im **SQL Editor** des Supabase-Dashboards in dieser Reihenfolge:
1. `supabase/migrations/0001_init.sql`
2. `supabase/migrations/0002_fix_rls_and_item_price.sql`
3. `supabase/migrations/0003_offers.sql`

Stelle anschließend unter **Authentication → Providers → Email** sicher, dass der E-Mail-OTP-Login aktiviert ist.

## 3. Xcode-Konfiguration (`Supabase.xcconfig`)

1. Kopiere die Vorlage:
   ```bash
   cp Config/Supabase.xcconfig.example Config/Supabase.xcconfig
   ```
2. Trage `SUPABASE_URL` und `SUPABASE_ANON_KEY` in `Config/Supabase.xcconfig` ein (diese Datei wird von Git ignoriert).
3. Weise `Supabase.xcconfig` in Xcode unter **Project → Info → Configurations** für `Debug` und `Release` zu.

## 4. Architektur-Roadmap

- **Phase 1 (Abgeschlossen):** Native SwiftUI-App mit E-Mail-OTP-Authentifizierung, Echtzeit-Einkaufslisten und Row-Level Security.
- **Phase 2 (Abgeschlossen):** Angebots-Datenmodell (`offers`), Händler-Filterung und Preisvergleichs-Ansicht.
- **Phase 3 (Geplant):** Automatisierter Angebots-Worker & unscharfer Artikelabgleich (`pg_trgm`) zwischen Einkaufsliste und aktuellen Wochenangeboten.
