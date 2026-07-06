//
//  ListItem.swift
//  PriceWatch
//

import Foundation

struct ListItem: Identifiable, Codable, Hashable {
    let id: UUID
    var listId: UUID
    var name: String
    var quantity: Double?
    var unit: String?
    var priceCents: Int?
    var isChecked: Bool
    var position: Int
    var createdBy: UUID
    var createdAt: Date
    var updatedAt: Date
    var checkedAt: Date?
}

struct NewListItem: Encodable {
    let listId: UUID
    let name: String
    let createdBy: UUID
    var quantity: Double?
    var unit: String?
    var priceCents: Int?
    var position: Int
}
