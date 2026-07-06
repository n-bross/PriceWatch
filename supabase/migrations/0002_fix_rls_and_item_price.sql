-- Fix: "infinite recursion detected in policy for relation list_members".
--
-- The old "owner manages members" policy queried list_members from within a
-- list_members policy, so every membership check re-triggered itself. The fix
-- is to route all membership checks through SECURITY DEFINER functions, which
-- run as the table owner and therefore bypass RLS (no recursion).
--
-- Also adds: price + styling columns for the AnyList-style redesign
-- (list color/icon, item price).

create or replace function public.is_list_member(_list_id uuid)
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select exists (
    select 1 from public.list_members
    where list_id = _list_id and user_id = auth.uid()
  );
$$;

create or replace function public.is_list_owner(_list_id uuid)
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select exists (
    select 1 from public.list_members
    where list_id = _list_id and user_id = auth.uid() and role = 'owner'
  );
$$;

-- Recreate every policy that previously queried list_members directly.

drop policy "list_members: owner manages members" on public.list_members;
create policy "list_members: owner manages members" on public.list_members
  for all
  using (public.is_list_owner(list_id))
  with check (public.is_list_owner(list_id));

drop policy "shopping_lists: members can read" on public.shopping_lists;
create policy "shopping_lists: members can read" on public.shopping_lists
  for select using (public.is_list_member(id));

drop policy "shopping_lists: members can update" on public.shopping_lists;
create policy "shopping_lists: members can update" on public.shopping_lists
  for update using (public.is_list_member(id));

drop policy "list_items: members can read" on public.list_items;
create policy "list_items: members can read" on public.list_items
  for select using (public.is_list_member(list_id));

drop policy "list_items: members can write" on public.list_items;
create policy "list_items: members can write" on public.list_items
  for all
  using (public.is_list_member(list_id))
  with check (public.is_list_member(list_id));

-- ---------------------------------------------------------------------------
-- Redesign support: colored/icon lists (AnyList style) and item prices.
-- ---------------------------------------------------------------------------

alter table public.shopping_lists
  add column color text not null default 'blue',
  add column icon text not null default 'cart';

alter table public.list_items
  add column price_cents integer check (price_cents is null or price_cents >= 0);
