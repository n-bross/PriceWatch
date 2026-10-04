-- Supports source counts and latest observation dates without reading payload_json.
-- Keep the older source index for compatibility with existing installations.
CREATE INDEX IF NOT EXISTS external_prices_source_date
    ON public.external_price_observations (source, price_date);
