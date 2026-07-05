//
//  ItemRowView.swift
//  PriceWatch
//

import SwiftUI

struct ItemRowView: View {
    let item: ListItem
    let onToggle: () -> Void

    var body: some View {
        HStack {
            Button(action: onToggle) {
                Image(systemName: item.isChecked ? "checkmark.circle.fill" : "circle")
                    .foregroundStyle(item.isChecked ? .green : .secondary)
            }
            .buttonStyle(.plain)

            VStack(alignment: .leading) {
                Text(item.name)
                    .strikethrough(item.isChecked)
                    .foregroundStyle(item.isChecked ? .secondary : .primary)
                if let quantity = item.quantity {
                    Text("\(quantity.formatted())\(item.unit.map { " \($0)" } ?? "")")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
        }
    }
}
