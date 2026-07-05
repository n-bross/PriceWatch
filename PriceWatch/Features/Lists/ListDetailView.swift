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

    let list: ShoppingList
    private var realtimeChannel: RealtimeChannelV2?
    private var watchTask: Task<Void, Never>?

    init(list: ShoppingList) {
        self.list = list
    }

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
        struct CheckedUpdate: Encodable {
            let isChecked: Bool
            let checkedAt: Date?
        }
        do {
            try await supabase
                .from("list_items")
                .update(CheckedUpdate(isChecked: !item.isChecked, checkedAt: item.isChecked ? nil : Date()))
                .eq("id", value: item.id)
                .execute()
            await loadItems()
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func deleteItems(at offsets: IndexSet) async {
        let idsToDelete = offsets.map { items[$0].id }
        do {
            try await supabase
                .from("list_items")
                .delete()
                .in("id", values: idsToDelete)
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

    init(list: ShoppingList) {
        _viewModel = StateObject(wrappedValue: ListDetailViewModel(list: list))
    }

    var body: some View {
        VStack {
            List {
                ForEach(viewModel.items) { item in
                    ItemRowView(item: item) {
                        Task { await viewModel.toggleChecked(item) }
                    }
                }
                .onDelete { offsets in
                    Task { await viewModel.deleteItems(at: offsets) }
                }
            }

            HStack {
                TextField("Neues Item", text: $newItemName)
                    .textFieldStyle(.roundedBorder)
                Button("Hinzufügen") {
                    let name = newItemName.trimmingCharacters(in: .whitespaces)
                    guard !name.isEmpty else { return }
                    newItemName = ""
                    Task { await viewModel.addItem(name: name) }
                }
                .disabled(newItemName.trimmingCharacters(in: .whitespaces).isEmpty)
            }
            .padding()
        }
        .navigationTitle(viewModel.list.name)
        .task { await viewModel.start() }
        .onDisappear { Task { await viewModel.stop() } }
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
