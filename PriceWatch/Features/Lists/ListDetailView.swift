//
//  ListDetailView.swift
//  PriceWatch
//

import SwiftUI
import Supabase

@MainActor
final class ListDetailViewModel: ObservableObject {
    @Published var items: [ListItem] = []
    @Published var errorMessage: String?
    /// Best current offer per open item, keyed by lowercased item name.
    @Published var offerMatches: [String: OfferMatch] = [:]

    let list: ShoppingList
    private var realtimeChannel: RealtimeChannelV2?
    private var watchTask: Task<Void, Never>?

    init(list: ShoppingList) {
        self.list = list
    }

    var openItems: [ListItem] { items.filter { !$0.isChecked } }
    var checkedItems: [ListItem] { items.filter { $0.isChecked } }

    /// Sum of all known prices of still-open items, in cents.
    var openTotalCents: Int { openItems.compactMap(\.priceCents).reduce(0, +) }
    var openItemsWithPriceCount: Int { openItems.filter { $0.priceCents != nil }.count }

    func start() async {
        await loadItems()
        await subscribeToChanges()
    }

    func stop() async {
        watchTask?.cancel()
        if let realtimeChannel {
            await realtimeChannel.unsubscribe()
        }
    }

    func loadItems() async {
        do {
            items = try await supabase
                .from("list_items")
                .select()
                .eq("list_id", value: list.id)
                .order("position")
                .execute()
                .value
        } catch {
            errorMessage = error.localizedDescription
        }
        await matchOffers()
    }

    /// Fetches the best matching current offer for every open item
    /// (server-side pg_trgm matching). Best-effort: failures never surface.
    private func matchOffers() async {
        let names = Array(Set(openItems.map(\.name)))
        guard !names.isEmpty else {
            offerMatches = [:]
            return
        }
        do {
            let matches: [OfferMatch] = try await supabase
                .rpc("match_offers", params: ["p_names": names])
                .execute()
                .value
            offerMatches = Dictionary(
                matches.filter { $0.similarity >= 0.25 }
                    .map { ($0.queryName.lowercased(), $0) },
                uniquingKeysWith: { first, _ in first }
            )
        } catch {
            offerMatches = [:]
        }
    }

    func offer(for item: ListItem) -> OfferMatch? {
        offerMatches[item.name.lowercased()]
    }

    func addItem(name: String) async {
        guard let session = try? await supabase.auth.session else { return }
        let newItem = NewListItem(
            listId: list.id,
            name: name,
            createdBy: session.user.id,
            position: items.count
        )
        do {
            try await supabase.from("list_items").insert(newItem).execute()
            await loadItems()
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func toggleChecked(_ item: ListItem) async {
        let update: [String: AnyJSON] = [
            "is_checked": .bool(!item.isChecked),
            "checked_at": item.isChecked ? .null : .string(ISO8601DateFormatter().string(from: Date())),
        ]
        do {
            try await supabase
                .from("list_items")
                .update(update)
                .eq("id", value: item.id)
                .execute()
            await loadItems()
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func updateItem(_ item: ListItem, name: String, quantity: Double?, unit: String?, priceCents: Int?) async {
        // Explicit AnyJSON values so clearing a field sends a real NULL
        // (Encodable structs drop nil keys entirely).
        let update: [String: AnyJSON] = [
            "name": .string(name),
            "quantity": quantity.map { .double($0) } ?? .null,
            "unit": unit.map { .string($0) } ?? .null,
            "price_cents": priceCents.map { .integer($0) } ?? .null,
        ]
        do {
            try await supabase
                .from("list_items")
                .update(update)
                .eq("id", value: item.id)
                .execute()
            await loadItems()
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func deleteItem(_ item: ListItem) async {
        do {
            try await supabase
                .from("list_items")
                .delete()
                .eq("id", value: item.id)
                .execute()
            await loadItems()
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func subscribeToChanges() async {
        let channel = supabase.realtimeV2.channel("list_items_changes_\(list.id)")
        let changes = channel.postgresChange(
            AnyAction.self,
            schema: "public",
            table: "list_items",
            filter: "list_id=eq.\(list.id)"
        )
        await channel.subscribe()
        realtimeChannel = channel

        watchTask = Task { [weak self] in
            for await _ in changes {
                await self?.loadItems()
            }
        }
    }
}

struct ListDetailView: View {
    @StateObject private var viewModel: ListDetailViewModel
    @State private var newItemName = ""
    @State private var editingItem: ListItem?
    @FocusState private var addFieldFocused: Bool

    private let accentColor: Color

    init(list: ShoppingList) {
        _viewModel = StateObject(wrappedValue: ListDetailViewModel(list: list))
        accentColor = Color(listSlug: list.color)
    }

    var body: some View {
        List {
            if viewModel.items.isEmpty {
                ContentUnavailableView(
                    "Noch keine Artikel",
                    systemImage: viewModel.list.icon,
                    description: Text("Füge oben deinen ersten Artikel hinzu.")
                )
                .listRowSeparator(.hidden)
            }

            if !viewModel.openItems.isEmpty {
                Section {
                    ForEach(viewModel.openItems) { item in
                        row(for: item)
                    }
                } header: {
                    banner("Zu kaufen (\(viewModel.openItems.count))", color: accentColor)
                }
            }

            if !viewModel.checkedItems.isEmpty {
                Section {
                    ForEach(viewModel.checkedItems) { item in
                        row(for: item)
                    }
                } header: {
                    banner("Erledigt (\(viewModel.checkedItems.count))", color: Color(.systemGray3))
                }
            }
        }
        .listStyle(.insetGrouped)
        .safeAreaInset(edge: .top) {
            addBar
        }
        .safeAreaInset(edge: .bottom) {
            totalBar
        }
        .navigationTitle(viewModel.list.name)
        .navigationBarTitleDisplayMode(.large)
        .tint(accentColor)
        .task { await viewModel.start() }
        .onDisappear { Task { await viewModel.stop() } }
        .sheet(item: $editingItem) { item in
            ItemEditSheet(item: item, accentColor: accentColor) { name, quantity, unit, priceCents in
                await viewModel.updateItem(item, name: name, quantity: quantity, unit: unit, priceCents: priceCents)
            }
            .presentationDetents([.medium])
        }
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

    private func row(for item: ListItem) -> some View {
        ItemRowView(
            item: item,
            accentColor: accentColor,
            offer: viewModel.offer(for: item),
            onToggle: { Task { await viewModel.toggleChecked(item) } },
            onEdit: { editingItem = item }
        )
        .contentShape(Rectangle())
        .onTapGesture { Task { await viewModel.toggleChecked(item) } }
        .swipeActions(edge: .trailing) {
            Button(role: .destructive) {
                Task { await viewModel.deleteItem(item) }
            } label: {
                Label("Löschen", systemImage: "trash")
            }
        }
    }

    /// AnyList-style colored section banner.
    private func banner(_ text: String, color: Color) -> some View {
        Text(text)
            .font(.footnote.weight(.semibold))
            .textCase(nil)
            .foregroundStyle(.white)
            .frame(maxWidth: .infinity)
            .padding(.vertical, 5)
            .background(color, in: RoundedRectangle(cornerRadius: 6))
            .listRowInsets(EdgeInsets(top: 4, leading: 0, bottom: 6, trailing: 0))
    }

    private var addBar: some View {
        HStack(spacing: 8) {
            TextField("＋ Artikel hinzufügen …", text: $newItemName)
                .focused($addFieldFocused)
                .textFieldStyle(.plain)
                .padding(.horizontal, 14)
                .padding(.vertical, 9)
                .background(Color(.systemBackground), in: Capsule())
                .overlay(Capsule().strokeBorder(Color(.systemGray4)))
                .onSubmit(addCurrentItem)

            if !newItemName.trimmingCharacters(in: .whitespaces).isEmpty {
                Button(action: addCurrentItem) {
                    Image(systemName: "plus.circle.fill")
                        .font(.system(size: 30))
                        .foregroundStyle(accentColor)
                }
                .buttonStyle(.plain)
            }
        }
        .padding(.horizontal)
        .padding(.vertical, 8)
        .background(.bar)
    }

    /// AnyList-style bottom bar: remaining estimated total, always visible.
    private var totalBar: some View {
        HStack {
            if viewModel.openItemsWithPriceCount < viewModel.openItems.count && viewModel.openItemsWithPriceCount > 0 {
                Text("\(viewModel.openItemsWithPriceCount) von \(viewModel.openItems.count) mit Preis")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            Spacer()
            Text("Verbleibend: \(euroString(cents: viewModel.openTotalCents))")
                .font(.subheadline.weight(.semibold))
                .monospacedDigit()
        }
        .padding(.horizontal)
        .padding(.vertical, 10)
        .background(.bar)
    }

    private func addCurrentItem() {
        let name = newItemName.trimmingCharacters(in: .whitespaces)
        guard !name.isEmpty else { return }
        newItemName = ""
        addFieldFocused = true
        Task { await viewModel.addItem(name: name) }
    }
}

struct ItemEditSheet: View {
    let item: ListItem
    let accentColor: Color
    let onSave: (String, Double?, String?, Int?) async -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var name: String
    @State private var quantity: Double?
    @State private var unit: String
    @State private var priceEuros: Double?

    init(item: ListItem, accentColor: Color, onSave: @escaping (String, Double?, String?, Int?) async -> Void) {
        self.item = item
        self.accentColor = accentColor
        self.onSave = onSave
        _name = State(initialValue: item.name)
        _quantity = State(initialValue: item.quantity)
        _unit = State(initialValue: item.unit ?? "")
        _priceEuros = State(initialValue: item.priceCents.map { Double($0) / 100 })
    }

    var body: some View {
        NavigationStack {
            Form {
                Section("Artikel") {
                    TextField("Name", text: $name)
                }
                Section("Details") {
                    TextField("Menge", value: $quantity, format: .number)
                        .keyboardType(.decimalPad)
                    TextField("Einheit (z. B. kg, Stück)", text: $unit)
                    TextField("Preis in €", value: $priceEuros, format: .number)
                        .keyboardType(.decimalPad)
                }
            }
            .navigationTitle("Artikel bearbeiten")
            .navigationBarTitleDisplayMode(.inline)
            .tint(accentColor)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Abbrechen") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Sichern") {
                        let trimmedName = name.trimmingCharacters(in: .whitespaces)
                        let trimmedUnit = unit.trimmingCharacters(in: .whitespaces)
                        guard !trimmedName.isEmpty else { return }
                        Task {
                            await onSave(
                                trimmedName,
                                quantity,
                                trimmedUnit.isEmpty ? nil : trimmedUnit,
                                priceEuros.map { Int(($0 * 100).rounded()) }
                            )
                            dismiss()
                        }
                    }
                    .fontWeight(.semibold)
                }
            }
        }
    }
}
