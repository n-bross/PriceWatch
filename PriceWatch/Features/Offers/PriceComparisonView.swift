import SwiftUI
import Foundation

struct ComparedProducts: Decodable {
    let items: [ComparedProduct]
    let total: Int
}

struct ComparedProduct: Decodable, Identifiable {
    let key: String
    let name: String
    let packageLabel: String?
    let ean: String?
    let prices: [ComparedPrice]
    var id: String { key }
}

struct ComparedPrice: Decodable {
    let retailer: String
    let priceCents: Int
    let currency: String
    let priceQualifier: String?
    let sourceUrl: String
    let scope: String
    let channel: String?
    let postalCode: String?
    let storeId: String?
    let priceDate: String?
    let validUntil: String?
    let requiresMembership: Bool
    let conditions: String?
    let bonusCreditCents: Int?

    var channelLabel: String {
        switch channel {
        case "pickup": return "Abholung"
        case "delivery": return "Lieferung"
        case "online": return "Online"
        case "instore", "store": return "Filiale"
        case "advertised": return "Prospekt"
        case "app": return "App"
        default:
            return scope == "online" ? "Online" : "Händlerangabe"
        }
    }
}

enum PriceComparisonAPI {
    static let deployedURL = "https://vps.tail179a46.ts.net:9450"
    static var defaultURL: String {
        if let configured = Bundle.main.object(forInfoDictionaryKey: "PRICEWATCH_API_URL") as? String,
           configured.hasPrefix("https://") { return configured }
        return deployedURL
    }

    static func requestURL(baseURL: String, query: String, postalCode: String,
                           includeMembership: Bool, offset: Int = 0) throws -> URL {
        guard var url = URLComponents(string: baseURL.trimmingCharacters(in: .whitespacesAndNewlines)),
              url.scheme == "https", let host = url.host, !host.isEmpty,
              url.user == nil, url.password == nil else {
            throw PriceComparisonError.invalidServer
        }
        guard postalCode.range(of: "^[0-9]{5}$", options: .regularExpression) != nil else {
            throw PriceComparisonError.invalidPostalCode
        }
        url.path = url.path.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        url.path = "/" + (url.path.isEmpty ? "" : url.path + "/") + "v1/compare"
        url.fragment = nil
        url.queryItems = [
            URLQueryItem(name: "q", value: query.trimmingCharacters(in: .whitespacesAndNewlines)),
            URLQueryItem(name: "postal_code", value: postalCode),
            URLQueryItem(name: "include_history", value: "false"),
            URLQueryItem(name: "include_membership", value: String(includeMembership)),
            URLQueryItem(name: "limit", value: "20"),
            URLQueryItem(name: "offset", value: String(offset))
        ]
        guard let result = url.url else { throw PriceComparisonError.invalidServer }
        return result
    }
}

enum PriceComparisonError: LocalizedError {
    case invalidServer, invalidPostalCode, unavailable

    var errorDescription: String? {
        switch self {
        case .invalidServer: return "Bitte in den Einstellungen eine gültige HTTPS-Serveradresse eintragen."
        case .invalidPostalCode: return "Bitte eine fünfstellige Postleitzahl eingeben."
        case .unavailable: return "Der Preisserver konnte die Suche nicht beantworten. Bitte erneut versuchen."
        }
    }
}

struct PriceComparisonView: View {
    @AppStorage("priceAPIURL") private var server = PriceComparisonAPI.defaultURL
    @AppStorage("pricePostalCode") private var postalCode = "85567"
    @State private var query = ""
    @State private var includeMembership = false
    @State private var items: [ComparedProduct] = []
    @State private var total = 0
    @State private var nextOffset = 0
    @State private var searched = false
    @State private var loading = false
    @State private var errorMessage: String?
    @State private var searchTask: Task<Void, Never>?
    @State private var requestID = UUID()
    @State private var loadedQuery = ""

    var body: some View {
        NavigationStack {
            List {
                Section {
                    HStack {
                        Text("Postleitzahl")
                        TextField("85567", text: $postalCode)
                            .keyboardType(.numberPad)
                            .multilineTextAlignment(.trailing)
                    }
                    Toggle("App- und Kundenkartenpreise", isOn: $includeMembership)
                    Button("Preise suchen") { search() }
                        .disabled(query.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                } footer: {
                    Text("Angebote und Preisbeobachtungen der letzten 7 Tage. Abhol-, Online- und Filialpreise können abweichen.")
                }

                if let errorMessage {
                    Section {
                        Text(errorMessage).foregroundStyle(.red)
                        Text("Für den voreingestellten Server muss Tailscale auf diesem Gerät verbunden sein.")
                            .font(.caption).foregroundStyle(.secondary)
                        Button("Erneut versuchen") { search() }
                    }
                }
                if loading { ProgressView("Preise werden geladen …") }
                if searched && items.isEmpty && !loading && errorMessage == nil {
                    ContentUnavailableView("Keine Preise gefunden", systemImage: "magnifyingglass",
                        description: Text("Versuche einen anderen Produktnamen oder eine EAN."))
                }
                if !searched {
                    Text("Suche beispielsweise nach Milch, Nudeln oder einer EAN.")
                        .foregroundStyle(.secondary)
                }
                if !items.isEmpty {
                    Text("\(total) Treffer für „\(loadedQuery)“")
                        .font(.caption).foregroundStyle(.secondary)
                }
                ForEach(items) { product in
                    Section {
                        if product.prices.isEmpty {
                            Text("Für dieses Produkt liegen noch keine aktuellen Preise vor.")
                                .font(.caption).foregroundStyle(.secondary)
                        }
                        ForEach(Array(product.prices.enumerated()), id: \.offset) { _, price in
                            ComparisonPriceRow(price: price)
                        }
                    } header: {
                        VStack(alignment: .leading) {
                            Text(product.name)
                            if let package = product.packageLabel { Text(package) }
                            if let ean = product.ean { Text("EAN \(ean)") }
                        }
                    }
                }
                if nextOffset < total && !loading {
                    Button("Weitere Ergebnisse laden") { search(loadMore: true) }
                }
            }
            .navigationTitle("Preisvergleich")
            .searchable(text: $query, prompt: "Produktname oder EAN")
            .onSubmit(of: .search) { search() }
            .onChange(of: server) { _, _ in resetResults() }
            .onChange(of: postalCode) { _, _ in resetResults() }
            .onChange(of: includeMembership) { _, _ in resetResults() }
            .onChange(of: query) { _, _ in resetResults() }
            .onDisappear { searchTask?.cancel(); loading = false }
        }
    }

    private func resetResults() {
        searchTask?.cancel()
        requestID = UUID()
        items = []; total = 0; nextOffset = 0; searched = false; loading = false; errorMessage = nil
    }

    private func search(loadMore: Bool = false) {
        let term = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !term.isEmpty else { return }
        searchTask?.cancel()
        let token = UUID()
        requestID = token
        if !loadMore { items = []; total = 0; nextOffset = 0 }
        let offset = nextOffset
        loading = true
        searched = true
        errorMessage = nil
        searchTask = Task { @MainActor in
            defer { if requestID == token { loading = false } }
            do {
                let url = try PriceComparisonAPI.requestURL(baseURL: server, query: term,
                    postalCode: postalCode, includeMembership: includeMembership, offset: offset)
                let (data, response) = try await URLSession.shared.data(for: URLRequest(url: url, timeoutInterval: 60))
                try Task.checkCancellation()
                guard let http = response as? HTTPURLResponse, http.statusCode == 200 else {
                    throw PriceComparisonError.unavailable
                }
                let decoder = JSONDecoder()
                decoder.keyDecodingStrategy = .convertFromSnakeCase
                let result = try decoder.decode(ComparedProducts.self, from: data)
                guard requestID == token else { return }
                let existing = Set(items.map(\.key))
                items += result.items.filter { !existing.contains($0.key) }
                total = result.total
                nextOffset = result.items.isEmpty ? result.total : offset + result.items.count
                loadedQuery = term
            } catch {
                guard !Task.isCancelled, requestID == token else { return }
                errorMessage = error.localizedDescription
            }
        }
    }
}

private struct ComparisonPriceRow: View {
    let price: ComparedPrice

    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            HStack {
                Text(price.retailer).fontWeight(.semibold)
                Spacer()
                Text((price.priceQualifier == "from" ? "ab " : "") +
                     (Double(price.priceCents) / 100).formatted(.currency(code: price.currency)))
                    .fontWeight(.semibold).monospacedDigit()
            }
            Text(price.channelLabel + (price.requiresMembership ? " · App/Kundenkarte" : ""))
                .font(.caption).foregroundStyle(.secondary)
            if let postalCode = price.postalCode {
                Text("PLZ \(postalCode)" + (price.storeId.map { " · Markt \($0)" } ?? ""))
                    .font(.caption)
            }
            if let date = price.priceDate { Text("Beobachtet am \(date)").font(.caption) }
            if let date = price.validUntil { Text("Angebot bis \(date)").font(.caption) }
            if let conditions = price.conditions { Text(conditions).font(.caption).foregroundStyle(.secondary) }
            if let bonus = price.bonusCreditCents, bonus > 0 {
                Text("Zusätzliches Bonusguthaben: \((Double(bonus) / 100).formatted(.currency(code: price.currency)))")
                    .font(.caption)
            }
            if let url = URL(string: price.sourceUrl), url.scheme == "https" {
                Link("Preisquelle öffnen", destination: url).font(.caption)
            }
        }
        .padding(.vertical, 3)
    }
}
