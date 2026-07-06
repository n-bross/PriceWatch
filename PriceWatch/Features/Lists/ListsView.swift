//
//  ListsView.swift
//  PriceWatch
//

import SwiftUI

struct ListsView: View {
    @StateObject private var viewModel = ListsViewModel()
    @State private var isAddingList = false

    var body: some View {
        NavigationStack {
            Group {
                if viewModel.lists.isEmpty {
                    ContentUnavailableView(
                        "Noch keine Listen",
                        systemImage: "cart",
                        description: Text("Erstelle mit + deine erste Einkaufsliste.")
                    )
                } else {
                    List {
                        ForEach(viewModel.lists) { list in
                            NavigationLink(value: list) {
                                ListRowView(list: list)
                            }
                            .swipeActions(edge: .trailing) {
                                Button(role: .destructive) {
                                    Task { await viewModel.deleteList(list) }
                                } label: {
                                    Label("Löschen", systemImage: "trash")
                                }
                            }
                        }
                    }
                    .listStyle(.insetGrouped)
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
            .sheet(isPresented: $isAddingList) {
                NewListSheet { name, color, icon in
                    await viewModel.createList(name: name, color: color, icon: icon)
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
    }
}

struct ListRowView: View {
    let list: ShoppingList

    var body: some View {
        HStack(spacing: 14) {
            ZStack {
                Circle()
                    .fill(Color(listSlug: list.color).gradient)
                    .frame(width: 42, height: 42)
                Image(systemName: list.icon)
                    .font(.system(size: 18, weight: .semibold))
                    .foregroundStyle(.white)
            }
            Text(list.name)
                .font(.headline)
        }
        .padding(.vertical, 4)
    }
}

struct NewListSheet: View {
    let onCreate: (String, String, String) async -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var name = ""
    @State private var color = ListStyleOptions.colorSlugs[0]
    @State private var icon = ListStyleOptions.icons[0]

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("Name der Liste", text: $name)
                }

                Section("Farbe") {
                    HStack(spacing: 12) {
                        ForEach(ListStyleOptions.colorSlugs, id: \.self) { slug in
                            Circle()
                                .fill(Color(listSlug: slug).gradient)
                                .frame(width: 32, height: 32)
                                .overlay {
                                    if slug == color {
                                        Image(systemName: "checkmark")
                                            .font(.caption.bold())
                                            .foregroundStyle(.white)
                                    }
                                }
                                .onTapGesture { color = slug }
                        }
                    }
                }

                Section("Symbol") {
                    LazyVGrid(columns: Array(repeating: GridItem(.flexible()), count: 8), spacing: 12) {
                        ForEach(ListStyleOptions.icons, id: \.self) { symbol in
                            Image(systemName: symbol)
                                .font(.system(size: 18))
                                .frame(width: 32, height: 32)
                                .background(
                                    symbol == icon ? Color(listSlug: color).opacity(0.25) : .clear,
                                    in: RoundedRectangle(cornerRadius: 8)
                                )
                                .onTapGesture { icon = symbol }
                        }
                    }
                }
            }
            .navigationTitle("Neue Liste")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Abbrechen") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Erstellen") {
                        let trimmed = name.trimmingCharacters(in: .whitespaces)
                        guard !trimmed.isEmpty else { return }
                        Task {
                            await onCreate(trimmed, color, icon)
                            dismiss()
                        }
                    }
                    .fontWeight(.semibold)
                    .disabled(name.trimmingCharacters(in: .whitespaces).isEmpty)
                }
            }
        }
    }
}

#Preview {
    ListsView()
}
