//
//  Theme.swift
//  PriceWatch
//
//  Shared styling helpers for the AnyList-style look: list colors/icons
//  and price formatting.
//

import SwiftUI

enum ListStyleOptions {
    /// Color slugs stored in shopping_lists.color.
    static let colorSlugs = ["blue", "red", "green", "orange", "purple", "pink", "teal", "indigo"]

    /// SF Symbol names stored in shopping_lists.icon.
    static let icons = ["cart", "basket", "fork.knife", "house", "gift", "pills", "pawprint", "leaf"]
}

extension Color {
    init(listSlug: String) {
        switch listSlug {
        case "red": self = .red
        case "green": self = .green
        case "orange": self = .orange
        case "purple": self = .purple
        case "pink": self = .pink
        case "teal": self = .teal
        case "indigo": self = .indigo
        default: self = .blue
        }
    }
}

/// Formats cents as a localized Euro amount, e.g. 249 -> "2,49 €".
func euroString(cents: Int) -> String {
    (Decimal(cents) / 100).formatted(.currency(code: "EUR"))
}
