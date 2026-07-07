-- PriceWatch Phase 2/3 (first slice): offers table + fuzzy matching.
--
-- Offers are written by the ingestion worker (service role) only — clients
-- get read-only access. Matching list items against offers happens server-side
-- via match_offers() using pg_trgm on the unaccented, lowercased names.
--
-- Includes a small demo seed so the app is testable before the Marktguru
-- worker (Phase 2 proper) exists; the worker will replace these rows.

create table public.offers (
  id uuid primary key default gen_random_uuid(),
  retailer text not null,
  name text not null,
  normalized_name text generated always as (
    lower(public.immutable_unaccent(trim(name)))
  ) stored,
  price_cents integer not null check (price_cents >= 0),
  regular_price_cents integer check (regular_price_cents is null or regular_price_cents >= 0),
  unit text,
  valid_from date not null default current_date,
  valid_until date not null,
  created_at timestamptz not null default now()
);

create index offers_normalized_name_trgm
  on public.offers using gin (normalized_name gin_trgm_ops);

create index offers_valid_until_idx on public.offers (valid_until);

alter table public.offers enable row level security;

-- Read-only for app users (incl. guest/anonymous sessions); no client writes.
create policy "offers: anyone can read" on public.offers
  for select using (true);

-- Best current offer per queried name. Uses trigram similarity plus a
-- substring fallback so "Pommes" matches "McCain Pommes Frites".
create or replace function public.match_offers(p_names text[])
returns table (
  query_name text,
  offer_id uuid,
  retailer text,
  offer_name text,
  price_cents integer,
  unit text,
  valid_until date,
  similarity real
)
language sql
stable
as $$
  select
    q.name,
    o.id,
    o.retailer,
    o.name,
    o.price_cents,
    o.unit,
    o.valid_until,
    similarity(o.normalized_name, lower(public.immutable_unaccent(trim(q.name))))
  from unnest(p_names) as q(name)
  join lateral (
    select *
    from public.offers o
    where o.valid_until >= current_date
      and (
        o.normalized_name % lower(public.immutable_unaccent(trim(q.name)))
        or o.normalized_name like '%' || lower(public.immutable_unaccent(trim(q.name))) || '%'
      )
    order by
      similarity(o.normalized_name, lower(public.immutable_unaccent(trim(q.name)))) desc,
      o.price_cents asc
    limit 1
  ) o on true;
$$;

-- Demo seed (replaced by the ingestion worker in Phase 2).
insert into public.offers (retailer, name, price_cents, regular_price_cents, unit, valid_until) values
  ('Lidl',  'McCain Pommes Frites',          199, 299, '750 g',   current_date + 6),
  ('Lidl',  'Bio Bananen',                   129, 179, '1 kg',    current_date + 6),
  ('Lidl',  'Gouda jung am Stück',           499, 699, '800 g',   current_date + 6),
  ('REWE',  'Persil Color Megaperls',        1299, 1899, '17 WL', current_date + 5),
  ('REWE',  'Rama Original',                 149, 239, '400 g',   current_date + 5),
  ('REWE',  'Jacobs Krönung Kaffee gemahlen', 499, 799, '500 g',  current_date + 5),
  ('ALDI',  'Milch 3,5%',                    89, 115, '1 l',      current_date + 4),
  ('ALDI',  'Nutella',                       299, 399, '450 g',   current_date + 4),
  ('ALDI',  'Hähnchenbrustfilet',            599, 799, '1 kg',    current_date + 4),
  ('EDEKA', 'Butter Deutsche Markenbutter',  159, 229, '250 g',   current_date + 7),
  ('EDEKA', 'Joghurt griechischer Art',      99, 149, '500 g',    current_date + 7),
  ('EDEKA', 'Äpfel Elstar',                  199, 279, '2 kg',    current_date + 7);
