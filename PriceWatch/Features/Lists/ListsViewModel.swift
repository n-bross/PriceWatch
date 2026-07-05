//
//  ListsViewModel.swift
//  PriceWatch
//

import Foundation
import Supabase

@MainActor
final class ListsViewModel: ObservableObject {
    @Published var lists: [ShoppingList] = []
    @Published var errorMessage: String?

    private var realtimeChannel: RealtimeChannelV2?
    private var watchTask: Task<Void, Never>?

    func start() async {
        await loadLists()
        await subscribeToChanges()
    }

    func stop() async {
        watchTask?.cancel()
        if let realtimeChannel {
            await realtimeChannel.unsubscribe()
        }
    }

    func loadLists() async {
        do {
            lists = try await supabase
                .from("shopping_lists")
                .select()
                .order("created_at")
                .execute()
                .value
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func createList(name: String) async {
        guard let session = try? await supabase.auth.session else { return }
        do {
            try await supabase
                .from("shopping_lists")
                .insert(NewShoppingList(ownerId: session.user.id, name: name))
                .execute()
            await loadLists()
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func deleteLists(at offsets: IndexSet) async {
        let idsToDelete = offsets.map { lists[$0].id }
        do {
            try await supabase
                .from("shopping_lists")
                .delete()
                .in("id", values: idsToDelete)
                .execute()
            await loadLists()
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    /// Reloads the list overview whenever any list changes (created elsewhere,
    /// e.g. on another device, or shared with us).
    private func subscribeToChanges() async {
        let channel = supabase.realtimeV2.channel("shopping_lists_changes")
        let changes = channel.postgresChange(AnyAction.self, schema: "public", table: "shopping_lists")
        await channel.subscribe()
        realtimeChannel = channel

        watchTask = Task { [weak self] in
            for await _ in changes {
                await self?.loadLists()
            }
        }
    }
}
