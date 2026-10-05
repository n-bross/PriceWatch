-- Price API catalog. Independent of legacy/demo public.offers.


CREATE TABLE price_catalog (
  id VARCHAR NOT NULL,
  source VARCHAR NOT NULL,
  retailer VARCHAR NOT NULL,
  source_product_id VARCHAR NOT NULL,
  name VARCHAR NOT NULL,
  normalized_name VARCHAR NOT NULL,
  brand VARCHAR,
  ean VARCHAR,
  kind VARCHAR NOT NULL,
  price_cents INTEGER NOT NULL,
  regular_price_cents INTEGER,
  deposit_cents INTEGER,
  currency VARCHAR NOT NULL,
  package_label VARCHAR,
  unit_price_cents NUMERIC(12, 2),
  unit_price_unit VARCHAR,
  valid_from DATE NOT NULL,
  valid_until DATE NOT NULL,
  scope VARCHAR NOT NULL,
  postal_code VARCHAR,
  store_id VARCHAR,
  requires_membership BOOLEAN NOT NULL,
  conditions VARCHAR,
  source_url VARCHAR NOT NULL,
  observed_at TIMESTAMP WITH TIME ZONE NOT NULL,
  is_listed BOOLEAN DEFAULT 'true' NOT NULL,
  PRIMARY KEY (id)
);

CREATE INDEX price_catalog_ean ON price_catalog (ean);

CREATE INDEX price_catalog_location ON price_catalog (postal_code, store_id);

CREATE INDEX price_catalog_lookup ON price_catalog (retailer, kind, valid_until);

CREATE TABLE price_source_runs (
  source VARCHAR NOT NULL,
  last_attempt TIMESTAMP WITH TIME ZONE NOT NULL,
  last_success TIMESTAMP WITH TIME ZONE,
  status VARCHAR NOT NULL,
  message VARCHAR,
  count INTEGER NOT NULL,
  PRIMARY KEY (source)
);

alter table public.price_catalog
  add constraint price_catalog_money check (
    price_cents >= 0 and (regular_price_cents is null or regular_price_cents >= 0)
    and (deposit_cents is null or deposit_cents >= 0)
    and (unit_price_cents is null or unit_price_cents >= 0) and currency = 'EUR'
  ),
  add constraint price_catalog_dates check (valid_until >= valid_from),
  add constraint price_catalog_kind check (kind in ('regular', 'offer')),
  add constraint price_catalog_scope check (
    (scope = 'chain_advertised' and postal_code is null and store_id is null)
    or (scope = 'postal_code' and postal_code is not null
        and postal_code ~ '^[0-9]{5}$' and store_id is null)
    or (scope = 'store' and store_id is not null)
  ),
  add constraint price_catalog_unit check (
    (unit_price_cents is null and unit_price_unit is null)
    or (unit_price_cents is not null and unit_price_unit is not null
        and unit_price_unit in ('kg', 'l', 'item'))
  );

-- Raw catalog and worker status are backend-only. Public clients use the API,
-- which enforces freshness, validity, membership and location filters.
alter table public.price_catalog enable row level security;
alter table public.price_source_runs enable row level security;
revoke all on public.price_catalog, public.price_source_runs from anon, authenticated;
grant all on public.price_catalog, public.price_source_runs to service_role;
-- The server connects as the database owner (or another dedicated backend role).
-- Never expose DATABASE_URL or PRICEWATCH_INGEST_KEY to the iOS application.
