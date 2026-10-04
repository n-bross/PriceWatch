-- External observations may lack store identity, price date or offer validity.
CREATE TABLE external_price_observations (
    id VARCHAR PRIMARY KEY,
    source VARCHAR NOT NULL,
    retailer VARCHAR NOT NULL,
    ean VARCHAR,
    name VARCHAR NOT NULL,
    normalized_name VARCHAR NOT NULL,
    price_cents INTEGER NOT NULL CHECK (price_cents >= 0),
    price_date VARCHAR,
    postal_code VARCHAR,
    store_id VARCHAR,
    payload_json TEXT NOT NULL
);
CREATE INDEX external_prices_ean_date ON external_price_observations (ean, price_date);
CREATE INDEX external_prices_source ON external_price_observations (source);
ALTER TABLE public.external_price_observations ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.external_price_observations FROM anon, authenticated;
GRANT ALL ON public.external_price_observations TO service_role;
