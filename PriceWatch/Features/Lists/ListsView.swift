//
//  ListsView.swift
//  PriceWatch
//

import SwiftUI

struct ListsView: View {
    @StateObject private var viewModel = ListsViewModel()
    @State private var newListName = ""
    @State private var isAddingList = false

    var body: some View {
        NavigationStack {
            List {
                ForEach(viewModel.lists) { list in
                    NavigationLink(list.name, value: list)
                }
                .onDelete { offsets in
                    Task { await viewModel.deleteLists(at: offsets) }
                }
            }
            .navigationTitle("Meine Listen")
            .navigationDestination(for: ShoppingList.self) { list in
                ListDetailView(list: list)
            }
            .toolbar {
                ToolbarItem(placement: .primaryAction) {
                    Button {
                        isAddingList = true
                    } label: {
                        Image(systemName: "plus")
                    }
                }
            }
            .task { await viewModel.start() }
            .alert("Neue Liste", isPresented: $isAddingList) {
                TextField("Name", text: $newListName)
                Button("Erstellen") {
                    let name = newListName.trimmingCharacters(in: .whitespaces)
                    newListName = ""
                    guard !name.isEmpty else { return }
                    Task { await viewModel.createList(name: name) }
                }
                Button("Abbrechen", role: .cancel) { newListName = "" }
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
    }
}

#Preview {
    ListsView()
}
