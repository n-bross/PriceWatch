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

/// Our tables use snake_case columns (owner_id, created_at, …) while the Swift
/// models use camelCase. Supabase's default PostgREST coders only configure a
/// date strategy and do NOT convert keys, so we layer snake_case conversion on
/// top while preserving Supabase's date handling.
private let databaseDecoder: JSONDecoder = {
    let base = PostgrestClient.Configuration.jsonDecoder
    let decoder = JSONDecoder()
    decoder.dateDecodingStrategy = base.dateDecodingStrategy
    decoder.keyDecodingStrategy = .convertFromSnakeCase
    return decoder
}()

private let databaseEncoder: JSONEncoder = {
    let base = PostgrestClient.Configuration.jsonEncoder
    let encoder = JSONEncoder()
    encoder.dateEncodingStrategy = base.dateEncodingStrategy
    encoder.keyEncodingStrategy = .convertToSnakeCase
    return encoder
}()

let supabase = SupabaseClient(
    supabaseURL: SupabaseConfig.url,
    supabaseKey: SupabaseConfig.anonKey,
    options: SupabaseClientOptions(
        db: SupabaseClientOptions.DatabaseOptions(
            encoder: databaseEncoder,
            decoder: databaseDecoder
        )
    )
)
