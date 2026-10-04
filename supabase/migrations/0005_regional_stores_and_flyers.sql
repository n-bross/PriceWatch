-- Regional store candidates and searchable official prospect documents.


CREATE TABLE price_area_stores (
  area_postal_code VARCHAR NOT NULL,
  retailer VARCHAR NOT NULL,
  store_id VARCHAR NOT NULL,
  name VARCHAR NOT NULL,
  postal_code VARCHAR NOT NULL,
  address VARCHAR NOT NULL,
  latitude NUMERIC(10, 7),
  longitude NUMERIC(10, 7),
  distance_km NUMERIC(8, 2),
  PRIMARY KEY (area_postal_code, retailer, store_id)
);

alter table public.price_area_stores enable row level security;
revoke all on public.price_area_stores from anon, authenticated;
grant all on public.price_area_stores to service_role;

CREATE TABLE price_flyers (
  id VARCHAR NOT NULL,
  retailer VARCHAR NOT NULL,
  title VARCHAR NOT NULL,
  source_url VARCHAR NOT NULL,
  valid_from DATE NOT NULL,
  valid_until DATE NOT NULL,
  scope VARCHAR NOT NULL,
  postal_code VARCHAR,
  store_id VARCHAR,
  region_label VARCHAR,
  observed_at TIMESTAMP WITH TIME ZONE NOT NULL,
  page_count INTEGER NOT NULL,
  needs_ocr_pages INTEGER NOT NULL,
  PRIMARY KEY (id)
);

alter table public.price_flyers enable row level security;
revoke all on public.price_flyers from anon, authenticated;
grant all on public.price_flyers to service_role;

CREATE TABLE price_flyer_pages (
  flyer_id VARCHAR NOT NULL,
  page INTEGER NOT NULL,
  text TEXT NOT NULL,
  normalized_text TEXT NOT NULL,
  method VARCHAR NOT NULL,
  PRIMARY KEY (flyer_id, page),
  FOREIGN KEY(flyer_id) REFERENCES price_flyers (id) ON DELETE CASCADE
);

alter table public.price_flyer_pages enable row level security;
revoke all on public.price_flyer_pages from anon, authenticated;
grant all on public.price_flyer_pages to service_role;
