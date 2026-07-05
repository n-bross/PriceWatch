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
        VStack(spacing: 16) {
            Text("PriceWatch")
                .font(.largeTitle.bold())

            switch viewModel.stage {
            case .enterEmail:
                TextField("E-Mail", text: $email)
                    .textContentType(.emailAddress)
                    .keyboardType(.emailAddress)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .textFieldStyle(.roundedBorder)

                Button("Code senden") {
                    Task { await viewModel.requestCode(email: email) }
                }
                .buttonStyle(.borderedProminent)
                .disabled(email.isEmpty || viewModel.isLoading)

            case .enterCode(let sentTo):
                Text("Code an \(sentTo) gesendet")
                    .font(.footnote)
                    .foregroundStyle(.secondary)

                TextField("6-stelliger Code", text: $code)
                    .keyboardType(.numberPad)
                    .textFieldStyle(.roundedBorder)

                Button("Anmelden") {
                    Task { await viewModel.verifyCode(code, email: sentTo) }
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
        .padding()
    }
}

#Preview {
    AuthView()
}
