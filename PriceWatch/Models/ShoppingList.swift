//
//  ShoppingList.swift
//  PriceWatch
//

import Foundation

struct ShoppingList: Identifiable, Codable, Hashable {
    let id: UUID
    var ownerId: UUID
    var name: String
    var createdAt: Date
    var updatedAt: Date
}

struct NewShoppingList: Encodable {
    let ownerId: UUID
    let name: String
}
