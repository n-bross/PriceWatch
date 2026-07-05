//
//  AuthViewModel.swift
//  PriceWatch
//

import Foundation
import Supabase

@MainActor
final class AuthViewModel: ObservableObject {
    enum Stage {
        case enterEmail
        case enterCode(email: String)
    }

    @Published var stage: Stage = .enterEmail
    @Published var isLoading = false
    @Published var errorMessage: String?

    /// Sends a one-time login code to the given email address.
    func requestCode(email: String) async {
        isLoading = true
        errorMessage = nil
        defer { isLoading = false }

        do {
            try await supabase.auth.signInWithOTP(email: email)
            stage = .enterCode(email: email)
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    /// Verifies the 6-digit code the user received by email.
    func verifyCode(_ code: String, email: String) async {
        isLoading = true
        errorMessage = nil
        defer { isLoading = false }

        do {
            try await supabase.auth.verifyOTP(email: email, token: code, type: .email)
            // A successful verification updates the shared session; AuthGate
            // observes that via supabase.auth.authStateChanges.
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func reset() {
        stage = .enterEmail
        errorMessage = nil
    }
}
