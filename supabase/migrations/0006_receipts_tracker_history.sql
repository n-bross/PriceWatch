-- Receipt verification, source tracking and observed price change history.


CREATE TABLE price_versions (
	id VARCHAR NOT NULL, 
	price_id VARCHAR NOT NULL, 
	source VARCHAR NOT NULL, 
	observed_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	event VARCHAR NOT NULL, 
	snapshot_json VARCHAR NOT NULL, 
	PRIMARY KEY (id)
)

;
CREATE INDEX price_versions_lookup ON price_versions (price_id, observed_at);
alter table public.price_versions enable row level security;
revoke all on public.price_versions from anon, authenticated;
grant all on public.price_versions to service_role;


CREATE TABLE price_receipts (
	id VARCHAR NOT NULL, 
	content_hash VARCHAR NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	metadata_json TEXT NOT NULL, 
	text TEXT NOT NULL, 
	lines_json TEXT NOT NULL, 
	comparisons_json TEXT NOT NULL, 
	confirmed BOOLEAN NOT NULL, 
	extraction_method VARCHAR NOT NULL, 
	PRIMARY KEY (id)
)

;
alter table public.price_receipts enable row level security;
revoke all on public.price_receipts from anon, authenticated;
grant all on public.price_receipts to service_role;


CREATE TABLE price_source_watches (
	id VARCHAR NOT NULL, 
	retailer VARCHAR NOT NULL, 
	mode VARCHAR NOT NULL, 
	url VARCHAR NOT NULL, 
	checked_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	changed_at TIMESTAMP WITH TIME ZONE, 
	fingerprint VARCHAR, 
	etag VARCHAR, 
	last_modified VARCHAR, 
	status VARCHAR NOT NULL, 
	message TEXT, 
	PRIMARY KEY (id)
)

;
alter table public.price_source_watches enable row level security;
revoke all on public.price_source_watches from anon, authenticated;
grant all on public.price_source_watches to service_role;


CREATE TABLE price_receipt_rechecks (
	receipt_id VARCHAR NOT NULL, 
	retailer VARCHAR NOT NULL, 
	postal_code VARCHAR, 
	requested_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	processed_at TIMESTAMP WITH TIME ZONE, 
	status VARCHAR NOT NULL, 
	message TEXT, 
	PRIMARY KEY (receipt_id)
)

;
alter table public.price_receipt_rechecks enable row level security;
revoke all on public.price_receipt_rechecks from anon, authenticated;
grant all on public.price_receipt_rechecks to service_role;

