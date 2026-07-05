-- PriceWatch Phase 0: profiles, shopping lists, list membership/sharing, list items.
-- Retailers/offers tables are added in a later migration (Phase 2).

create extension if not exists pg_trgm;
create extension if not exists unaccent;
create extension if not exists pgcrypto;

-- ---------------------------------------------------------------------------
-- profiles: one row per auth.users, created automatically via trigger below.
-- ---------------------------------------------------------------------------
create table public.profiles (
  id uuid primary key references auth.users (id) on delete cascade,
  display_name text,
  home_zip text,
  created_at timestamptz not null default now()
);

alter table public.profiles enable row level security;

create policy "profiles: read own" on public.profiles
  for select using (auth.uid() = id);

create policy "profiles: update own" on public.profiles
  for update using (auth.uid() = id);

-- Auto-create a profile row whenever a new auth user signs up.
create function public.handle_new_user()
returns trigger
language plpgsql
security definer set search_path = public
as $$
begin
  insert into public.profiles (id) values (new.id);
  return new;
end;
$$;

create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- ---------------------------------------------------------------------------
-- shopping_lists
-- ---------------------------------------------------------------------------
create table public.shopping_lists (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references public.profiles (id) on delete cascade,
  name text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.shopping_lists enable row level security;

-- ---------------------------------------------------------------------------
-- list_members: drives both sharing and RLS for lists/items.
-- ---------------------------------------------------------------------------
create table public.list_members (
  list_id uuid not null references public.shopping_lists (id) on delete cascade,
  user_id uuid not null references public.profiles (id) on delete cascade,
  role text not null default 'owner' check (role in ('owner', 'editor')),
  invited_at timestamptz not null default now(),
  primary key (list_id, user_id)
);

alter table public.list_members enable row level security;

create policy "list_members: read own memberships" on public.list_members
  for select using (auth.uid() = user_id);

create policy "list_members: owner manages members" on public.list_members
  for all using (
    exists (
      select 1 from public.list_members m
      where m.list_id = list_members.list_id
        and m.user_id = auth.uid()
        and m.role = 'owner'
    )
  );

-- Auto-add the creator as owner member whenever a list is created.
create function public.handle_new_list()
returns trigger
language plpgsql
security definer set search_path = public
as $$
begin
  insert into public.list_members (list_id, user_id, role)
  values (new.id, new.owner_id, 'owner');
  return new;
end;
$$;

create trigger on_shopping_list_created
  after insert on public.shopping_lists
  for each row execute function public.handle_new_list();

create policy "shopping_lists: members can read" on public.shopping_lists
  for select using (
    exists (
      select 1 from public.list_members m
      where m.list_id = shopping_lists.id and m.user_id = auth.uid()
    )
  );

create policy "shopping_lists: authenticated users can create" on public.shopping_lists
  for insert with check (auth.uid() = owner_id);

create policy "shopping_lists: members can update" on public.shopping_lists
  for update using (
    exists (
      select 1 from public.list_members m
      where m.list_id = shopping_lists.id and m.user_id = auth.uid()
    )
  );

create policy "shopping_lists: owner can delete" on public.shopping_lists
  for delete using (auth.uid() = owner_id);

-- ---------------------------------------------------------------------------
-- list_items
-- ---------------------------------------------------------------------------
create table public.list_items (
  id uuid primary key default gen_random_uuid(),
  list_id uuid not null references public.shopping_lists (id) on delete cascade,
  name text not null,
  normalized_name text generated always as (
    lower(unaccent(trim(name)))
  ) stored,
  quantity numeric,
  unit text,
  is_checked boolean not null default false,
  position integer not null default 0,
  created_by uuid not null references public.profiles (id),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  checked_at timestamptz
);

create index list_items_normalized_name_trgm
  on public.list_items using gin (normalized_name gin_trgm_ops);

create index list_items_list_id_idx on public.list_items (list_id);

alter table public.list_items enable row level security;

create policy "list_items: members can read" on public.list_items
  for select using (
    exists (
      select 1 from public.list_members m
      where m.list_id = list_items.list_id and m.user_id = auth.uid()
    )
  );

create policy "list_items: members can write" on public.list_items
  for all using (
    exists (
      select 1 from public.list_members m
      where m.list_id = list_items.list_id and m.user_id = auth.uid()
    )
  );

-- ---------------------------------------------------------------------------
-- Realtime: broadcast changes on lists and items to subscribed clients.
-- ---------------------------------------------------------------------------
alter publication supabase_realtime add table public.shopping_lists;
alter publication supabase_realtime add table public.list_items;
