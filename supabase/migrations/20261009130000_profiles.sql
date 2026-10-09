-- Profiles: one application-level row per authenticated user.
--
-- Security model (see docs/ARCHITECTURE.md §5-6):
--   * Browsers and phones never query tables directly; all data goes through the FastAPI service,
--     which runs every user request as the `authenticated` role with the verified JWT claims.
--     RLS is therefore a second, independent line of defence behind the API's own ownership checks.
--   * Supabase grants new `public` tables to anon/authenticated/service_role by default, so access
--     is revoked explicitly below and granted back with the minimum privileges needed.
--   * Rows are created by a trigger on auth.users, never by clients.

create function public.set_updated_at()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

comment on function public.set_updated_at() is
  'Shared BEFORE UPDATE trigger that maintains updated_at.';

create table public.profiles (
  id uuid primary key references auth.users (id) on delete cascade,
  display_name text
    check (display_name is null or char_length(btrim(display_name)) between 1 and 80),
  locale text not null default 'en'
    check (locale ~ '^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$'),
  timezone text not null default 'Asia/Kolkata'
    check (char_length(timezone) between 1 and 64),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

comment on table public.profiles is
  'Application settings for a user. id is the auth.users id; deleting the auth user deletes the profile and, by cascade, all of that user''s data.';

create trigger profiles_set_updated_at
  before update on public.profiles
  for each row execute function public.set_updated_at();

-- Row Level Security: deny by default, then allow owners only.
alter table public.profiles enable row level security;

create policy profiles_select_own on public.profiles
  for select to authenticated
  using (id = (select auth.uid()));

create policy profiles_update_own on public.profiles
  for update to authenticated
  using (id = (select auth.uid()))
  with check (id = (select auth.uid()));

-- Least privilege. No INSERT or DELETE for clients (the trigger creates rows; account deletion
-- goes through the auth user), and UPDATE only on the user-editable columns.
revoke all on table public.profiles from anon, authenticated;
grant select on table public.profiles to authenticated;
grant update (display_name, locale, timezone) on table public.profiles to authenticated;

-- Create the profile automatically whenever a user signs up. SECURITY DEFINER with an empty
-- search_path so it cannot be hijacked; it never raises on odd metadata, because a failing trigger
-- would block sign-up.
create function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  insert into public.profiles (id, display_name)
  values (
    new.id,
    nullif(left(btrim(coalesce(new.raw_user_meta_data ->> 'display_name', '')), 80), '')
  )
  on conflict (id) do nothing;
  return new;
end;
$$;

comment on function public.handle_new_user() is
  'Creates the public.profiles row for a new auth.users row.';

revoke all on function public.handle_new_user() from public, anon, authenticated;

create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- Users that signed up before this migration existed.
insert into public.profiles (id)
select id from auth.users
on conflict (id) do nothing;
