<div align="center">

# 🛒 PriceWatch

**Native iOS-Einkaufslisten- & Angebotsvergleichs-App mit Echtzeit-Synchronisation (SwiftUI + Supabase)**

[![Swift](https://img.shields.io/badge/Swift_6-F05138?style=flat-square&logo=swift&logoColor=white)](https://swift.org/)
[![SwiftUI](https://img.shields.io/badge/SwiftUI-007AFF?style=flat-square&logo=apple&logoColor=white)](https://developer.apple.com/xcode/swiftui/)
[![Supabase](https://img.shields.io/badge/Supabase_Realtime-3ECF8E?style=flat-square&logo=supabase&logoColor=white)](https://supabase.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL_(RLS)-4169E1?style=flat-square&logo=postgresql&logoColor=white)](https://www.postgresql.org/)

</div>

---

## 🎯 Überblick

**PriceWatch** kombiniert kollaborative Echtzeit-Einkaufslisten (inspiriert von *AnyList*) mit einer intelligenten Supermarkt-Angebotsübersicht für den deutschen Einzelhandel (REWE, ALDI, LIDL, EDEKA, Kaufland, Penny, Netto, dm).

### ✨ Kernfunktionen

- **⚡ Echtzeit-Einkaufslisten:** Gemeinsame Listen mit sofortiger Synchronisation über **Supabase Realtime** (`postgresChange`-Channels), automatischer Kategorisierung und kompakter AnyList-inspirierter Darstellung.
- **🏷️ Supermarkt-Angebote & Preisvergleich:** Durchsuchbare Wochenangebote nach Händler inkl. Grundpreis-Berechnung, Rabatt-Prozentanzeige (`discountPercent`) und direkter Übernahme auf die aktive Einkaufsliste.
- **🔐 Passwordless Auth & Row-Level Security (RLS):** Schneller Login per E-Mail-OTP (`verifyOTP`) und strikte Mandantentrennung direkt in PostgreSQL über Row-Level-Security-Policies.
- **🔄 Automatische Snake-/CamelCase-Serialisierung:** Maßgeschneiderte `PostgrestClient`-JSON-Coder verbinden idiomatische Swift-Modelle (`camelCase`) nahtlos mit PostgreSQL-Tabellenspalten (`snake_case`).

---

## 🏗️ Projektstruktur

```text
PriceWatch/
├── PriceWatch/
│   ├── Core/
│   │   ├── SupabaseClient.swift     # Supabase-Konfiguration & PostgREST JSON-Encoder/Decoder
│   │   └── Theme.swift              # Design-Tokens, Farben & Händler-Styling
│   ├── Models/
│   │   ├── ShoppingList.swift       # Einkaufslisten-Domänenmodell
│   │   ├── ListItem.swift           # Listenpositionen inkl. Preis, Menge, Einheit & Notiz
│   │   └── Offer.swift              # Aktionsangebote inkl. Rabatt- & Ablaufberechnung
│   └── Features/
│       ├── Auth/                    # Passwortloser E-Mail-OTP-Login (AuthView & AuthViewModel)
│       ├── Lists/                   # Listenübersicht, Detailansicht & Echtzeit-Sync
│       └── Offers/                  # Angebots-Browser mit Händler-Filter & Suche
├── Config/
│   └── Supabase.xcconfig.example    # Vorlage für Build-Konfiguration (URL & Anon-Key)
└── supabase/migrations/
    ├── 0001_init.sql                # Basis-Schema (shopping_lists, list_items) & RLS
    ├── 0002_fix_rls_and_item_price.sql
    └── 0003_offers.sql              # Angebots-Tabelle, Indizes & Demo-Datensätze
```

---

## 🚀 Setup & Lokale Entwicklung

### 1. Datenbank in Supabase einrichten

Spiele die SQL-Migrationen der Reihe nach über die Supabase CLI oder den SQL-Editor ein:

```bash
supabase db push
```

*(Alternativ `supabase/migrations/0001_init.sql` bis `0003_offers.sql` im Supabase SQL-Editor ausführen.)*

### 2. Xcode-Konfiguration anlegen

Kopiere die Beispielkonfiguration und trage deine Supabase-Projektdaten ein (`.xcconfig` ist in `.gitignore` ausgeschlossen):

```bash
cp Config/Supabase.xcconfig.example Config/Supabase.xcconfig
```

```ini
SUPABASE_URL = https:/$()/your-project-ref.supabase.co
SUPABASE_ANON_KEY = your-anon-public-key
```

### 3. Build & Ausführung

Öffne `PriceWatch.xcodeproj` in Xcode (ab iOS 17) oder kompiliere das Projekt über die Kommandozeile:

```bash
xcodebuild -project PriceWatch.xcodeproj -scheme PriceWatch \
  -destination 'platform=iOS Simulator,name=iPhone 16' build
```
