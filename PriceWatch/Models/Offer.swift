//
//  Offer.swift
//  PriceWatch
//

import Foundation

/// A current retail offer, written by the ingestion worker (Phase 2).
/// valid_from/valid_until are plain SQL dates ("2026-07-13"), which the
/// Supabase date decoder does not parse — kept as strings and formatted
/// for display via `germanDateString`.
struct Offer: Identifiable, Codable, Hashable {
    let id: UUID
    var retailer: String
    var name: String
    var priceCents: Int
    var regularPriceCents: Int?
    var unit: String?
    var validFrom: String
    var validUntil: String
}

/// One row of the match_offers() RPC: best current offer for a queried
/// list-item name.
struct OfferMatch: Codable, Hashable {
    var queryName: String
    var offerId: UUID
    var retailer: String
    var offerName: String
    var priceCents: Int
    var unit: String?
    var validUntil: String
    var similarity: Double
}

/// "2026-07-13" -> "13.07.", empty string if unparseable.
func germanDateString(sqlDate: String) -> String {
    let parser = DateFormatter()
    parser.dateFormat = "yyyy-MM-dd"
    parser.locale = Locale(identifier: "en_US_POSIX")
    guard let date = parser.date(from: sqlDate) else { return "" }
    let output = DateFormatter()
    output.dateFormat = "dd.MM."
    return output.string(from: date)
}
