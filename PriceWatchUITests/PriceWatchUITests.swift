//
//  PriceWatchUITests.swift
//  PriceWatchUITests
//
//  Created by Nico Bro on 22.02.24.
//

import XCTest

final class PriceWatchUITests: XCTestCase {

    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    private func snap(_ name: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    /// End-to-end walkthrough against the live Supabase backend:
    /// guest login -> tab bar -> offers load -> add item -> offer badge.
    func testGuestFlowTabsAndOfferMatching() throws {
        let app = XCUIApplication()
        app.launch()

        // Guest login (skipped if a session from a previous run still exists).
        let guestButton = app.buttons["Ohne Anmeldung testen (Gast)"]
        if guestButton.waitForExistence(timeout: 5) {
            guestButton.tap()
        }

        // Tab bar with all three tabs must appear.
        let listsTab = app.tabBars.buttons["Listen"]
        XCTAssertTrue(listsTab.waitForExistence(timeout: 15), "Tab-Bar erschien nicht nach Login")
        XCTAssertTrue(app.tabBars.buttons["Angebote"].exists)
        XCTAssertTrue(app.tabBars.buttons["Einstellungen"].exists)

        // Offers tab shows seeded retailers.
        app.tabBars.buttons["Angebote"].tap()
        XCTAssertTrue(
            app.staticTexts["Lidl"].waitForExistence(timeout: 10),
            "Angebote wurden nicht geladen"
        )
        snap("angebote-tab")

        // Open the first shopping list and add an item that has a matching offer.
        // On a fresh guest account (clean simulator clone) no list exists yet —
        // create one through the UI first.
        listsTab.tap()
        var firstList = app.collectionViews.cells.firstMatch
        if !firstList.waitForExistence(timeout: 5) {
            app.buttons["Neue Liste"].tap()
            let nameField = app.textFields["Name der Liste"]
            XCTAssertTrue(nameField.waitForExistence(timeout: 5), "Neue-Liste-Sheet fehlt")
            nameField.tap()
            nameField.typeText("Wocheneinkauf")
            app.buttons["Erstellen"].tap()
            firstList = app.collectionViews.cells.firstMatch
            XCTAssertTrue(firstList.waitForExistence(timeout: 10), "Liste wurde nicht erstellt")
        }
        firstList.tap()

        let addField = app.textFields.firstMatch
        XCTAssertTrue(addField.waitForExistence(timeout: 10), "Add-Feld fehlt")
        addField.tap()
        addField.typeText("Pommes\n")

        // The green offer badge must appear (server-side pg_trgm match).
        let badge = app.staticTexts.matching(
            NSPredicate(format: "label CONTAINS %@", "bei Lidl")
        ).firstMatch
        XCTAssertTrue(badge.waitForExistence(timeout: 15), "Angebots-Badge fehlt — Item-Insert oder match_offers fehlgeschlagen")
        snap("listen-detail-mit-badge")
    }
}
