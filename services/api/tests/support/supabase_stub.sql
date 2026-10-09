-- Minimal emulation of the parts of a Supabase project that StudyPilot's migrations depend on, so
-- the real migration files can be applied to a plain PostgreSQL in tests.
--
-- This is a TEST DOUBLE for the platform, not for StudyPilot's own code. It mirrors, as closely as
-- is practical:
--   * the API roles (anon, authenticated, service_role) and their schema usage,
--   * auth.users (only the columns our SQL touches) and auth.uid()/jwt()/role(),
--   * Supabase's default privileges: new public tables/functions/sequences are granted to all three
--     API roles, which is exactly why our migrations must revoke and re-grant explicitly.
-- The CI "supabase" job applies the same migrations to the real Supabase stack, which is the
-- authority; keep this file as small as possible.

create role anon nologin noinherit;
create role authenticated nologin noinherit;
create role service_role nologin noinherit bypassrls;

create schema extensions;
create schema auth;

grant usage on schema public to anon, authenticated, service_role;
grant usage on schema extensions to anon, authenticated, service_role;
grant usage on schema auth to anon, authenticated, service_role;

create table auth.users (
  id uuid primary key default gen_random_uuid(),
  email text,
  raw_app_meta_data jsonb not null default '{}'::jsonb,
  raw_user_meta_data jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

-- Same definitions as the Supabase platform: identity comes from the request.jwt.claims setting
-- that the API (like PostgREST) sets inside each transaction.
create function auth.uid()
returns uuid
language sql
stable
as $$
  select nullif(
    coalesce(
      nullif(current_setting('request.jwt.claim.sub', true), ''),
      (nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub')
    ),
    ''
  )::uuid
$$;

create function auth.role()
returns text
language sql
stable
as $$
  select coalesce(
    nullif(current_setting('request.jwt.claim.role', true), ''),
    (nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'role')
  )::text
$$;

create function auth.jwt()
returns jsonb
language sql
stable
as $$
  select coalesce(
    nullif(current_setting('request.jwt.claim', true), ''),
    nullif(current_setting('request.jwt.claims', true), '')
  )::jsonb
$$;

grant execute on function auth.uid(), auth.role(), auth.jwt() to anon, authenticated, service_role;

-- Supabase's default privileges for objects created by the postgres role in public.
alter default privileges for role postgres in schema public
  grant all on tables to anon, authenticated, service_role;
alter default privileges for role postgres in schema public
  grant all on functions to anon, authenticated, service_role;
alter default privileges for role postgres in schema public
  grant all on sequences to anon, authenticated, service_role;
