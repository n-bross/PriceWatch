//
//  PriceWatchTests.swift
//  PriceWatchTests
//
//  Created by Nico Bro on 22.02.24.
//

import XCTest
@testable import PriceWatch

final class PriceWatchTests: XCTestCase {

    func testComparisonRequestPreservesSearchAndChannelFilters() throws {
        let url = try PriceComparisonAPI.requestURL(baseURL: "https://example.org/",
            query: "Milch & Kakao", postalCode: "85567", includeMembership: false, offset: 20)
        let parts = try XCTUnwrap(URLComponents(url: url, resolvingAgainstBaseURL: false))
        let parameters = Dictionary(uniqueKeysWithValues: (parts.queryItems ?? []).map { ($0.name, $0.value ?? "") })
        XCTAssertEqual(parts.path, "/v1/compare")
        XCTAssertEqual(parameters["q"], "Milch & Kakao")
        XCTAssertEqual(parameters["postal_code"], "85567")
        XCTAssertEqual(parameters["include_history"], "false")
        XCTAssertEqual(parameters["include_membership"], "false")
        XCTAssertEqual(parameters["offset"], "20")
        XCTAssertThrowsError(try PriceComparisonAPI.requestURL(baseURL: "http://example.org",
            query: "Milch", postalCode: "85567", includeMembership: false))
        XCTAssertThrowsError(try PriceComparisonAPI.requestURL(baseURL: "https://example.org",
            query: "Milch", postalCode: "abc", includeMembership: false))
    }

    func testComparisonResponseKeepsPickupPriceAndBonusSeparate() throws {
        let data = Data(#"""
        {"total":1,"items":[{"key":"ean:3083681102499","name":"Goldmais",
          "package_label":"285 g","ean":"3083681102499","prices":[{
            "retailer":"REWE","price_cents":111,"currency":"EUR",
            "source_url":"https://www.rewe.de/p/goldmais/4203860",
            "scope":"store_channel","channel":"pickup","postal_code":"85567",
            "store_id":"461766","price_date":"2026-10-04","valid_until":null,
            "requires_membership":false,"bonus_credit_cents":15
          }]}]}
        """#.utf8)
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let page = try decoder.decode(ComparedProducts.self, from: data)
        let product = try XCTUnwrap(page.items.first)
        let price = try XCTUnwrap(product.prices.first)
        XCTAssertEqual(product.packageLabel, "285 g")
        XCTAssertEqual(price.priceCents, 111)
        XCTAssertEqual(price.bonusCreditCents, 15)
        XCTAssertEqual(price.channelLabel, "Abholung")
        XCTAssertEqual(price.storeId, "461766")
    }

    override func setUpWithError() throws {
        // Put setup code here. This method is called before the invocation of each test method in the class.
    }

    override func tearDownWithError() throws {
        // Put teardown code here. This method is called after the invocation of each test method in the class.
    }

    func testExample() throws {
        // This is an example of a functional test case.
        // Use XCTAssert and related functions to verify your tests produce the correct results.
        // Any test you write for XCTest can be annotated as throws and async.
        // Mark your test throws to produce an unexpected failure when your test encounters an uncaught error.
        // Mark your test async to allow awaiting for asynchronous code to complete. Check the results with assertions afterwards.
    }

    func testPerformanceExample() throws {
        // This is an example of a performance test case.
        measure {
            // Put the code you want to measure the time of here.
        }
    }

}
