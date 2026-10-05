-- Test fixture only: run in a fresh disposable database as its owner.
-- Supabase supplies these roles in production.
CREATE ROLE anon NOLOGIN;
CREATE ROLE authenticated NOLOGIN;
CREATE ROLE service_role NOLOGIN BYPASSRLS;
