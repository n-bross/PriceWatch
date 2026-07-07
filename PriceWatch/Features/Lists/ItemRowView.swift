//
//  ItemRowView.swift
//  PriceWatch
//

import SwiftUI

struct ItemRowView: View {
    let item: ListItem
    let accentColor: Color
    var offer: OfferMatch?
    let onToggle: () -> Void
    let onEdit: () -> Void

    private var detailText: String? {
        var parts: [String] = []
        if let quantity = item.quantity {
            parts.append("\(quantity.formatted())\(item.unit.map { " \($0)" } ?? "")")
        } else if let unit = item.unit {
            parts.append(unit)
        }
        return parts.isEmpty ? nil : parts.joined(separator: " · ")
    }

    var body: some View {
        HStack(spacing: 12) {
            Button(action: onToggle) {
                Image(systemName: item.isChecked ? "checkmark.circle.fill" : "circle")
                    .font(.title3)
                    .foregroundStyle(item.isChecked ? accentColor : Color.secondary)
                    .contentTransition(.symbolEffect(.replace))
            }
            .buttonStyle(.plain)

            VStack(alignment: .leading, spacing: 2) {
                Text(item.name)
                    .strikethrough(item.isChecked)
                    .foregroundStyle(item.isChecked ? .secondary : .primary)
                if let detailText {
                    Text(detailText)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                if let offer, !item.isChecked {
                    HStack(spacing: 4) {
                        Image(systemName: "percent")
                            .font(.system(size: 9, weight: .bold))
                        Text("\(euroString(cents: offer.priceCents)) bei \(offer.retailer)")
                            .font(.caption2.weight(.semibold))
                    }
                    .foregroundStyle(.white)
                    .padding(.horizontal, 6)
                    .padding(.vertical, 2)
                    .background(Color.green, in: Capsule())
                }
            }

            Spacer()

            if let cents = item.priceCents {
                Text(euroString(cents: cents))
                    .font(.subheadline.monospacedDigit())
                    .foregroundStyle(item.isChecked ? .secondary : .primary)
            }

            Button(action: onEdit) {
                Image(systemName: "pencil")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }
            .buttonStyle(.plain)
        }
        .padding(.vertical, 2)
    }
}
