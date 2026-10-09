-- Learning goals: what a user wants to learn, and the constraints of their schedule.
--
-- Ownership is enforced three ways: the API derives user_id from the verified token, RLS refuses
-- rows that are not the caller's, and (for child tables added later) composite foreign keys on
-- (id, user_id) make cross-user references impossible.
--
-- This migration grants clients SELECT and INSERT only. Editing, pausing and archiving arrive
-- with the endpoints that need them and add the matching UPDATE grant and policy at that time.

-- Languages are ISO 639-1/-3 style codes ("en", "hi", "or"). Which codes the product supports is
-- an application decision (and changes without a migration), so the database only enforces shape.
create function public.is_valid_language_list(langs text[])
returns boolean
language sql
immutable
parallel safe
set search_path = ''
as $$
  select langs is not null
    and cardinality(langs) between 1 and 5
    and array_position(langs, null) is null
    and coalesce((select bool_and(code ~ '^[a-z]{2,3}$') from unnest(langs) as code), false)
$$;

create table public.learning_goals (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.profiles (id) on delete cascade,
  title text not null
    check (char_length(btrim(title)) between 1 and 200),
  description text
    check (description is null or char_length(description) <= 2000),
  goal_type text not null default 'general'
    check (goal_type in (
      'exam', 'academic_subject', 'professional_skill', 'certification', 'interview', 'general'
    )),
  -- "unknown" exists so a guessed level is never stored as fact.
  current_level text not null default 'unknown'
    check (current_level in ('unknown', 'beginner', 'intermediate', 'advanced')),
  target_date date,
  daily_minutes integer not null default 60
    check (daily_minutes between 5 and 1440),
  preferred_languages text[] not null default array['en']::text[]
    check (public.is_valid_language_list(preferred_languages)),
  status text not null default 'active'
    check (status in ('active', 'paused', 'completed', 'archived')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  -- Target of composite foreign keys from future child tables (roadmaps, ...).
  constraint learning_goals_id_user_id_key unique (id, user_id)
);

comment on table public.learning_goals is
  'A learner''s goal. Owned by exactly one user; every child record carries the same user_id.';

-- Serves the dashboard list: one user's goals, newest first, keyset-paginated on (created_at, id).
create index learning_goals_user_list_idx
  on public.learning_goals (user_id, created_at desc, id desc);

create trigger learning_goals_set_updated_at
  before update on public.learning_goals
  for each row execute function public.set_updated_at();

alter table public.learning_goals enable row level security;

create policy learning_goals_select_own on public.learning_goals
  for select to authenticated
  using (user_id = (select auth.uid()));

create policy learning_goals_insert_own on public.learning_goals
  for insert to authenticated
  with check (user_id = (select auth.uid()));

-- Least privilege. INSERT is limited to the columns a client may choose: id, status and the
-- timestamps always come from the database defaults.
revoke all on table public.learning_goals from anon, authenticated;
grant select on table public.learning_goals to authenticated;
grant insert (
  user_id, title, description, goal_type, current_level, target_date, daily_minutes,
  preferred_languages
) on table public.learning_goals to authenticated;
