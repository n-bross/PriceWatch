//
//  AuthView.swift
//  PriceWatch
//

import SwiftUI

struct AuthView: View {
    @StateObject private var viewModel = AuthViewModel()
    @State private var email = ""
    @State private var code = ""

    var body: some View {
        VStack(spacing: 0) {
            Spacer()

            VStack(spacing: 12) {
                ZStack {
                    RoundedRectangle(cornerRadius: 20)
                        .fill(Color.blue.gradient)
                        .frame(width: 80, height: 80)
                    Image(systemName: "cart.fill")
                        .font(.system(size: 36, weight: .semibold))
                        .foregroundStyle(.white)
                }

                Text("PriceWatch")
                    .font(.largeTitle.bold())

                Text("Einkaufslisten mit Angebots-Radar")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }
            .padding(.bottom, 40)

            VStack(spacing: 16) {
                switch viewModel.stage {
                case .enterEmail:
                    TextField("E-Mail", text: $email)
                        .textContentType(.emailAddress)
                        .keyboardType(.emailAddress)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .padding(12)
                        .background(Color(.systemGray6), in: RoundedRectangle(cornerRadius: 12))

                    Button {
                        Task { await viewModel.requestCode(email: email) }
                    } label: {
                        Text("Code senden")
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, 6)
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(email.isEmpty || viewModel.isLoading)

                    Button("Ohne Anmeldung testen (Gast)") {
                        Task { await viewModel.continueAsGuest() }
                    }
                    .buttonStyle(.plain)
                    .font(.footnote)
                    .foregroundStyle(.blue)
                    .disabled(viewModel.isLoading)

                case .enterCode(let sentTo):
                    Text("Code an \(sentTo) gesendet")
                        .font(.footnote)
                        .foregroundStyle(.secondary)

                    TextField("6-stelliger Code", text: $code)
                        .keyboardType(.numberPad)
                        .textContentType(.oneTimeCode)
                        .multilineTextAlignment(.center)
                        .font(.title3.monospacedDigit())
                        .padding(12)
                        .background(Color(.systemGray6), in: RoundedRectangle(cornerRadius: 12))

                    Button {
                        Task { await viewModel.verifyCode(code, email: sentTo) }
                    } label: {
                        Text("Anmelden")
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, 6)
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(code.isEmpty || viewModel.isLoading)

                    Button("Andere E-Mail verwenden") {
                        viewModel.reset()
                        code = ""
                    }
                    .buttonStyle(.plain)
                    .font(.footnote)
                }

                if viewModel.isLoading {
                    ProgressView()
                }

                if let error = viewModel.errorMessage {
                    Text(error)
                        .font(.footnote)
                        .foregroundStyle(.red)
                        .multilineTextAlignment(.center)
                }
            }
            .padding(.horizontal, 32)

            Spacer()
            Spacer()
        }
    }
}

#Preview {
    AuthView()
}
