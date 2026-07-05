//
//  ContentView.swift
//  PriceWatch
//
//  Created by Nico Bro on 22.02.24.
//

import SwiftUI
import Supabase

struct ContentView: View {
    @State private var session: Session?

    var body: some View {
        Group {
            if session != nil {
                ListsView()
            } else {
                AuthView()
            }
        }
        .task {
            for await state in supabase.auth.authStateChanges {
                session = state.session
            }
        }
    }
}

#Preview {
    ContentView()
}
