//
//  SupabaseClient.swift
//  PriceWatch
//

import Foundation
import Supabase

enum SupabaseConfig {
    static var url: URL {
        guard
            let raw = Bundle.main.object(forInfoDictionaryKey: "SUPABASE_URL") as? String,
            let url = URL(string: raw),
            !raw.isEmpty
        else {
            fatalError("""
                Missing SUPABASE_URL. Copy Config/Supabase.xcconfig.example to \
                Config/Supabase.xcconfig, fill in your project's values, and make sure \
                it's assigned as the build configuration file (Project > Info > Configurations) \
                and its keys are exposed via Info.plist.
                """)
        }
        return url
    }

    static var anonKey: String {
        guard
            let key = Bundle.main.object(forInfoDictionaryKey: "SUPABASE_ANON_KEY") as? String,
            !key.isEmpty
        else {
            fatalError("Missing SUPABASE_ANON_KEY — see Config/Supabase.xcconfig.example")
        }
        return key
    }
}

let supabase = SupabaseClient(
    supabaseURL: SupabaseConfig.url,
    supabaseKey: SupabaseConfig.anonKey
)
