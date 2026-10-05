-- Product identities, provenance and confirmed retailer article mappings.


CREATE TABLE product_catalog (
	ean VARCHAR NOT NULL, 
	name VARCHAR NOT NULL, 
	normalized_name VARCHAR NOT NULL, 
	brand VARCHAR, 
	package_label VARCHAR, 
	countries_json TEXT NOT NULL, 
	reported_stores TEXT, 
	categories_json TEXT DEFAULT '[]' NOT NULL, 
	source VARCHAR NOT NULL, 
	source_url VARCHAR NOT NULL, 
	source_updated_at TIMESTAMP WITH TIME ZONE, 
	imported_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (ean)
)

;

CREATE INDEX product_catalog_name ON product_catalog (normalized_name);

alter table public.product_catalog enable row level security;

revoke all on public.product_catalog from anon, authenticated;

grant all on public.product_catalog to service_role;


CREATE TABLE product_retailer_articles (
	retailer VARCHAR NOT NULL, 
	source_product_id VARCHAR NOT NULL, 
	store_id VARCHAR DEFAULT '' NOT NULL, 
	ean VARCHAR NOT NULL, 
	source_url VARCHAR NOT NULL, 
	note VARCHAR, 
	observed_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (retailer, source_product_id, store_id)
)

;

CREATE INDEX product_retailer_articles_ean ON product_retailer_articles (ean);

alter table public.product_retailer_articles enable row level security;

revoke all on public.product_retailer_articles from anon, authenticated;

grant all on public.product_retailer_articles to service_role;


CREATE TABLE product_catalog_sources (
	ean VARCHAR NOT NULL, 
	source VARCHAR NOT NULL, 
	payload_json TEXT NOT NULL, 
	source_url VARCHAR NOT NULL, 
	source_updated_at TIMESTAMP WITH TIME ZONE, 
	imported_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (ean, source)
)

;

alter table public.product_catalog_sources enable row level security;

revoke all on public.product_catalog_sources from anon, authenticated;

grant all on public.product_catalog_sources to service_role;
