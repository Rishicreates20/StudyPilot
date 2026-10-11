-- Goal lifecycle (edit, pause, complete, archive, delete) and persistent learning preferences.
--
-- The API enforces these rules first and gives friendly errors; the database enforces them again
-- so that a bug in application code still cannot produce an illegal state:
--
--   * status moves only along legal transitions (trigger),
--   * an archived goal is read-only until it is restored (trigger),
--   * completed_at / archived_at are set by the database when the status changes, never by a
--     client (they are not in the UPDATE grant), and always agree with the status (check),
--   * only an archived goal can be deleted (policy): deleting is a second, deliberate step.
--
-- Clients (the API's `authenticated` role) get UPDATE on the editable columns and DELETE, and
-- nothing else. Ownership is unchanged: every policy still requires user_id = auth.uid().

-- Which kinds of study material a learner wants. Like languages, the exact vocabulary is shaped
-- here (so garbage cannot be stored) but the API owns the user-facing wording.
create function public.is_valid_learning_preferences(prefs text[])
returns boolean
language sql
immutable
parallel safe
set search_path = ''
as $$
  select prefs is not null
    and cardinality(prefs) <= 3
    and array_position(prefs, null) is null
    and prefs <@ array['examples', 'quizzes', 'revision']::text[]
    and cardinality(prefs) = (select count(distinct p) from unnest(prefs) as p)
$$;

comment on function public.is_valid_learning_preferences(text[]) is
  'True for a duplicate-free subset of {examples, quizzes, revision}; the empty set is allowed.';

-- --- learning_goals -----------------------------------------------------------------------------

alter table public.learning_goals
  add column learning_preferences text[] not null
    default array['examples', 'quizzes', 'revision']::text[]
    check (public.is_valid_learning_preferences(learning_preferences)),
  add column completed_at timestamptz,
  add column archived_at timestamptz,
  add constraint learning_goals_completed_at_matches_status
    check ((status = 'completed') = (completed_at is not null)),
  add constraint learning_goals_archived_at_matches_status
    check ((status = 'archived') = (archived_at is not null));

create function public.learning_goals_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if tg_op = 'INSERT' then
    -- Rows normally start active; rows created in another state (imports, tests) still get the
    -- matching timestamp so the checks above hold.
    new.completed_at := case when new.status = 'completed' then coalesce(new.completed_at, now()) end;
    new.archived_at := case when new.status = 'archived' then coalesce(new.archived_at, now()) end;
    return new;
  end if;

  if new.status is distinct from old.status then
    if not (
      (old.status = 'active' and new.status in ('paused', 'completed', 'archived'))
      or (old.status = 'paused' and new.status in ('active', 'completed', 'archived'))
      or (old.status = 'completed' and new.status in ('active', 'archived'))
      or (old.status = 'archived' and new.status = 'active')
    ) then
      raise exception 'A goal cannot move from % to %.', old.status, new.status
        using errcode = 'check_violation', constraint = 'learning_goals_status_transition';
    end if;
    new.completed_at := case when new.status = 'completed' then now() end;
    new.archived_at := case when new.status = 'archived' then now() end;
  elsif old.status = 'archived' and (
    new.title is distinct from old.title
    or new.description is distinct from old.description
    or new.goal_type is distinct from old.goal_type
    or new.current_level is distinct from old.current_level
    or new.target_date is distinct from old.target_date
    or new.daily_minutes is distinct from old.daily_minutes
    or new.preferred_languages is distinct from old.preferred_languages
    or new.learning_preferences is distinct from old.learning_preferences
  ) then
    raise exception 'An archived goal cannot be edited. Restore it first.'
      using errcode = 'check_violation', constraint = 'learning_goals_archived_read_only';
  end if;

  return new;
end;
$$;

comment on function public.learning_goals_guard() is
  'Legal status transitions, read-only archived goals, and system-managed completed_at/archived_at.';

create trigger learning_goals_guard
  before insert or update on public.learning_goals
  for each row execute function public.learning_goals_guard();

create policy learning_goals_update_own on public.learning_goals
  for update to authenticated
  using (user_id = (select auth.uid()))
  with check (user_id = (select auth.uid()));

-- Deleting is only possible for archived goals: archive first, delete second.
create policy learning_goals_delete_own_archived on public.learning_goals
  for delete to authenticated
  using (user_id = (select auth.uid()) and status = 'archived');

grant insert (learning_preferences) on table public.learning_goals to authenticated;
grant update (
  title, description, goal_type, current_level, target_date, daily_minutes, preferred_languages,
  learning_preferences, status
) on table public.learning_goals to authenticated;
grant delete on table public.learning_goals to authenticated;

-- --- profiles: persistent preferences and onboarding ---------------------------------------------

alter table public.profiles
  add column onboarding_completed_at timestamptz,
  add column default_daily_minutes integer not null default 60
    check (default_daily_minutes between 10 and 480),
  add column preferred_languages text[] not null default array['en']::text[]
    check (public.is_valid_language_list(preferred_languages)),
  add column learning_preferences text[] not null
    default array['examples', 'quizzes', 'revision']::text[]
    check (public.is_valid_learning_preferences(learning_preferences));

comment on column public.profiles.onboarding_completed_at is
  'Set once, when the user finishes or skips onboarding. Null means onboarding is still due.';
comment on column public.profiles.default_daily_minutes is
  'Starting value for the daily study time of new goals.';

grant update (
  default_daily_minutes, preferred_languages, learning_preferences, onboarding_completed_at
) on table public.profiles to authenticated;

-- People who already created goals before onboarding existed should not be sent through it.
update public.profiles as p
set onboarding_completed_at = now()
where p.onboarding_completed_at is null
  and exists (select 1 from public.learning_goals as g where g.user_id = p.id);
