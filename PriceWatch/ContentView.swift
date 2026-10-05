//
//  ContentView.swift
//  PriceWatch
//
//  Created by Nico Bro on 22.02.24.
//

import SwiftUI
import Supabase

struct ContentView: View {
    @State private var session: Session?

    var body: some View {
        Group {
            if let session {
                MainTabView(session: session)
            } else {
                AuthView()
            }
        }
        .task {
            for await state in supabase.auth.authStateChanges {
                session = state.session
            }
        }
    }
}

struct MainTabView: View {
    let session: Session

    var body: some View {
        TabView {
            ListsView()
                .tabItem { Label("Listen", systemImage: "checklist") }

            OffersView()
                .tabItem { Label("Angebote", systemImage: "percent") }

            PriceComparisonView()
                .tabItem { Label("Preise", systemImage: "magnifyingglass") }

            SettingsView(session: session)
                .tabItem { Label("Einstellungen", systemImage: "gearshape") }
        }
    }
}

struct SettingsView: View {
    let session: Session
    @State private var isSigningOut = false
    @AppStorage("priceAPIURL") private var priceServer = PriceComparisonAPI.defaultURL

    private var accountLabel: String {
        session.user.email ?? "Gast (anonym)"
    }

    var body: some View {
        NavigationStack {
            Form {
                Section("Konto") {
                    LabeledContent("Angemeldet als", value: accountLabel)

                    Button(role: .destructive) {
                        isSigningOut = true
                        Task {
                            try? await supabase.auth.signOut()
                            isSigningOut = false
                        }
                    } label: {
                        if isSigningOut {
                            ProgressView()
                        } else {
                            Text("Abmelden")
                        }
                    }
                }

                Section("Preisvergleich") {
                    TextField("HTTPS-Serveradresse", text: $priceServer)
                        .keyboardType(.URL)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                    Button("Standardserver verwenden") { priceServer = PriceComparisonAPI.defaultURL }
                } footer: {
                    Text("Der Tab Preise nutzt denselben Datenbestand wie der Browser. Für den voreingestellten Server ist eine Tailscale-Verbindung erforderlich.")
                }

                Section {
                    LabeledContent("Version", value: appVersion)
                } footer: {
                    Text("PriceWatch — Einkaufslisten mit Angebots-Radar")
                }
            }
            .navigationTitle("Einstellungen")
        }
    }

    private var appVersion: String {
        let version = Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "?"
        let build = Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") as? String ?? "?"
        return "\(version) (\(build))"
    }
}

#Preview {
    ContentView()
}
