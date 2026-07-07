//
//  OffersView.swift
//  PriceWatch
//
//  Browse current retail offers, grouped by retailer.
//

import SwiftUI
import Supabase

@MainActor
final class OffersViewModel: ObservableObject {
    @Published var offers: [Offer] = []
    @Published var errorMessage: String?
    @Published var isLoading = false

    var retailers: [String] {
        Array(Set(offers.map(\.retailer))).sorted()
    }

    func offers(for retailer: String) -> [Offer] {
        offers.filter { $0.retailer == retailer }.sorted { $0.name < $1.name }
    }

    func load() async {
        isLoading = true
        defer { isLoading = false }
        do {
            offers = try await supabase
                .from("offers")
                .select("id, retailer, name, price_cents, regular_price_cents, unit, valid_from, valid_until")
                .gte("valid_until", value: sqlDateToday())
                .order("retailer")
                .execute()
                .value
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func sqlDateToday() -> String {
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyy-MM-dd"
        formatter.locale = Locale(identifier: "en_US_POSIX")
        return formatter.string(from: Date())
    }
}

struct OffersView: View {
    @StateObject private var viewModel = OffersViewModel()
    @State private var searchText = ""

    var body: some View {
        NavigationStack {
            Group {
                if viewModel.offers.isEmpty && !viewModel.isLoading {
                    ContentUnavailableView(
                        "Keine Angebote",
                        systemImage: "percent",
                        description: Text("Aktuell sind keine Angebote verfügbar.")
                    )
                } else {
                    List {
                        ForEach(filteredRetailers, id: \.self) { retailer in
                            Section(retailer) {
                                ForEach(filteredOffers(for: retailer)) { offer in
                                    OfferRowView(offer: offer)
                                }
                            }
                        }
                    }
                    .listStyle(.insetGrouped)
                }
            }
            .navigationTitle("Angebote")
            .searchable(text: $searchText, prompt: "Angebote durchsuchen")
            .refreshable { await viewModel.load() }
            .task { await viewModel.load() }
            .alert(
                "Fehler",
                isPresented: Binding(
                    get: { viewModel.errorMessage != nil },
                    set: { if !$0 { viewModel.errorMessage = nil } }
                )
            ) {
                Button("OK", role: .cancel) {}
            } message: {
                Text(viewModel.errorMessage ?? "")
            }
        }
    }

    private var filteredRetailers: [String] {
        viewModel.retailers.filter { !filteredOffers(for: $0).isEmpty }
    }

    private func filteredOffers(for retailer: String) -> [Offer] {
        let all = viewModel.offers(for: retailer)
        guard !searchText.isEmpty else { return all }
        return all.filter { $0.name.localizedCaseInsensitiveContains(searchText) }
    }
}

struct OfferRowView: View {
    let offer: Offer

    var body: some View {
        HStack(alignment: .center, spacing: 12) {
            VStack(alignment: .leading, spacing: 2) {
                Text(offer.name)
                HStack(spacing: 6) {
                    if let unit = offer.unit {
                        Text(unit)
                    }
                    Text("bis \(germanDateString(sqlDate: offer.validUntil))")
                }
                .font(.caption)
                .foregroundStyle(.secondary)
            }

            Spacer()

            VStack(alignment: .trailing, spacing: 2) {
                Text(euroString(cents: offer.priceCents))
                    .font(.subheadline.weight(.semibold).monospacedDigit())
                    .foregroundStyle(.green)
                if let regular = offer.regularPriceCents {
                    Text(euroString(cents: regular))
                        .font(.caption.monospacedDigit())
                        .foregroundStyle(.secondary)
                        .strikethrough()
                }
            }
        }
        .padding(.vertical, 2)
    }
}

#Preview {
    OffersView()
}
