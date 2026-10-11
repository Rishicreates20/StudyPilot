-- Lessons for roadmap topics, and the learner's progress through them.
--
-- Who writes what
--   * The API (role `authenticated`, acting as the signed-in learner) may queue a LESSON job for a
--     topic of its current roadmap, read its own lessons, and record its own study progress.
--   * The worker connects with the privileged database role (no row security) and is the only
--     writer of lessons, so a learner can never store lesson content directly.
--
-- Guarantees the database itself enforces, whatever the application does
--   * a lesson job names a topic (or optional extra) of the learner's CURRENT roadmap for that goal,
--     never a revision session and never someone else's item;
--   * at most one queued/running lesson job per topic, and still one roadmap job per goal;
--   * one lesson per job (a retried job cannot store a second), version numbers unique per topic,
--     at most one current version per topic;
--   * a stored lesson never changes: clients have no write privilege on `lessons` at all;
--   * progress belongs to one lesson and one learner, can only name that lesson's own sections,
--     can only be `completed` when every section is done, and is read-only on archived goals;
--   * deleting a goal removes its lessons and progress.

-- --- roadmap_items: a key a job can use to prove the item is the same learner's ----------------------

alter table public.roadmap_items
  add constraint roadmap_items_id_user_id_key unique (id, user_id);

-- --- generation_jobs: lesson jobs -------------------------------------------------------------------

alter table public.generation_jobs
  drop constraint generation_jobs_job_type_check;

alter table public.generation_jobs
  add constraint generation_jobs_job_type_check check (job_type in ('roadmap', 'lesson')),
  -- The roadmap item a lesson job writes a lesson for; null for roadmap jobs.
  add column item_id uuid,
  add constraint generation_jobs_item_fk
    foreign key (item_id, user_id) references public.roadmap_items (id, user_id)
    on delete cascade,
  add constraint generation_jobs_item_matches_type
    check ((job_type = 'lesson') = (item_id is not null));

-- One roadmap generation at a time per goal, as before; lessons are limited per topic instead, so
-- a learner can have a lesson being written while a roadmap is being revised.
drop index public.generation_jobs_one_active_per_goal;

create unique index generation_jobs_one_active_per_goal on public.generation_jobs (goal_id)
  where status in ('queued', 'running') and job_type = 'roadmap';

create unique index generation_jobs_one_active_per_item on public.generation_jobs (item_id)
  where status in ('queued', 'running') and item_id is not null;

create index generation_jobs_item_idx on public.generation_jobs (item_id, created_at desc)
  where item_id is not null;

-- A lesson job must point at a lessonable item of the goal's current roadmap. Runs as the caller
-- (SECURITY INVOKER): the caller can only see their own rows, which is exactly the check wanted.
create function public.generation_jobs_before_insert()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if new.job_type = 'lesson' and not exists (
    select 1
    from public.roadmap_items i
    join public.roadmaps r on r.id = i.roadmap_id and r.user_id = i.user_id
    where i.id = new.item_id
      and i.user_id = new.user_id
      and r.goal_id = new.goal_id
      and r.status = 'current'
      and i.kind <> 'revision'
  ) then
    raise exception 'A lesson job must name a topic of the goal''s current roadmap'
      using errcode = '23514', constraint = 'generation_jobs_lesson_target';
  end if;
  return new;
end;
$$;

create trigger generation_jobs_check_target
  before insert on public.generation_jobs
  for each row execute function public.generation_jobs_before_insert();

grant insert (item_id) on table public.generation_jobs to authenticated;

-- --- lessons ----------------------------------------------------------------------------------------

create table public.lessons (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.profiles (id) on delete cascade,
  roadmap_id uuid not null,
  item_id uuid not null,
  job_id uuid not null,
  -- 1, 2, 3 ... per topic. Regenerating is a NEW row; earlier versions are kept.
  version integer not null check (version >= 1),
  status text not null default 'current' check (status in ('current', 'superseded')),
  -- Copied out of `content` so lists can show it without parsing the document.
  title text not null check (char_length(btrim(title)) between 1 and 200),
  language text not null check (language ~ '^[a-z]{2,3}$'),
  -- The validated lesson document (see app/ai/lesson/schema.py). Its shape is checked by the API's
  -- Pydantic model before it is stored and again whenever it is read.
  content jsonb not null check (jsonb_typeof(content) = 'object'),
  -- Version of that document format, so old lessons stay readable if the format ever changes.
  content_version integer not null check (content_version >= 1),
  -- The ids of the lesson's sections ("s1", "s2" ...), in order; progress is recorded against them.
  section_ids text[] not null check (cardinality(section_ids) between 1 and 12),
  -- How a regeneration was asked to differ from the version it started from.
  adjust text check (adjust in ('simpler', 'more_examples', 'deeper')),
  revision_feedback text check (revision_feedback is null or char_length(revision_feedback) <= 300),
  based_on_lesson_id uuid,
  prompt_version text not null check (char_length(prompt_version) between 1 and 60),
  provider text not null check (char_length(provider) between 1 and 40),
  model_id text not null check (char_length(model_id) <= 120),
  -- True when a test double produced the content. The UI labels such lessons as samples.
  is_synthetic boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  -- Exactly one lesson per job: a retried or double-claimed job cannot store a second one.
  constraint lessons_job_id_key unique (job_id),
  constraint lessons_item_id_version_key unique (item_id, version),
  constraint lessons_id_user_id_key unique (id, user_id),
  constraint lessons_roadmap_fk
    foreign key (roadmap_id, user_id) references public.roadmaps (id, user_id)
    on delete cascade,
  constraint lessons_item_fk
    foreign key (item_id, roadmap_id) references public.roadmap_items (id, roadmap_id)
    on delete cascade,
  constraint lessons_job_fk
    foreign key (job_id, user_id) references public.generation_jobs (id, user_id)
    on delete cascade,
  constraint lessons_based_on_fk
    foreign key (based_on_lesson_id, user_id) references public.lessons (id, user_id)
    on delete set null (based_on_lesson_id)
);

comment on table public.lessons is
  'A generated, versioned lesson for one roadmap topic. Content is immutable; the worker is the only writer.';

-- At most one current version per topic.
create unique index lessons_one_current_per_item on public.lessons (item_id)
  where status = 'current';
create index lessons_roadmap_idx on public.lessons (roadmap_id);

create trigger lessons_set_updated_at
  before update on public.lessons
  for each row execute function public.set_updated_at();

alter table public.lessons enable row level security;

create policy lessons_select_own on public.lessons
  for select to authenticated
  using (user_id = (select auth.uid()));

revoke all on table public.lessons from anon, authenticated;
grant select on table public.lessons to authenticated;

-- --- lesson_progress --------------------------------------------------------------------------------

-- One row per lesson the learner has started. `current_section_id` is where to resume.
create table public.lesson_progress (
  lesson_id uuid primary key,
  user_id uuid not null,
  status text not null default 'in_progress' check (status in ('in_progress', 'completed')),
  completed_section_ids text[] not null default '{}'::text[]
    check (cardinality(completed_section_ids) <= 12),
  current_section_id text check (current_section_id is null or current_section_id ~ '^s[0-9]{1,2}$'),
  started_at timestamptz not null default now(),
  last_studied_at timestamptz not null default now(),
  completed_at timestamptz,
  constraint lesson_progress_completed_matches_status
    check ((status = 'completed') = (completed_at is not null)),
  constraint lesson_progress_lesson_fk
    foreign key (lesson_id, user_id) references public.lessons (id, user_id)
    on delete cascade
);

comment on table public.lesson_progress is
  'A learner''s place in, and completion of, one lesson version.';

create index lesson_progress_user_idx on public.lesson_progress (user_id, last_studied_at desc);

-- The rules progress must obey whatever wrote it. Runs as the caller (SECURITY INVOKER).
create function public.lesson_progress_before_write()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  sections text[];
  goal_status text;
begin
  select l.section_ids, g.status
    into sections, goal_status
    from public.lessons l
    join public.roadmaps r on r.id = l.roadmap_id
    join public.learning_goals g on g.id = r.goal_id
   where l.id = new.lesson_id;

  if sections is null then
    raise exception 'The lesson does not exist' using errcode = '23503';
  end if;
  if goal_status = 'archived' then
    raise exception 'The goal is archived; its lessons are read-only'
      using errcode = '23514', constraint = 'lesson_progress_goal_archived_read_only';
  end if;
  if not (new.completed_section_ids <@ sections)
     or (new.current_section_id is not null and not (new.current_section_id = any (sections))) then
    raise exception 'Progress can only name sections of its own lesson'
      using errcode = '23514', constraint = 'lesson_progress_unknown_section';
  end if;
  if cardinality(new.completed_section_ids)
       <> (select count(distinct s) from unnest(new.completed_section_ids) as s) then
    raise exception 'A section can only be marked done once'
      using errcode = '23514', constraint = 'lesson_progress_duplicate_section';
  end if;
  if new.status = 'completed' and not (sections <@ new.completed_section_ids) then
    raise exception 'A lesson is only complete when every section is done'
      using errcode = '23514', constraint = 'lesson_progress_incomplete_sections';
  end if;

  new.last_studied_at := now();
  return new;
end;
$$;

create trigger lesson_progress_rules
  before insert or update on public.lesson_progress
  for each row execute function public.lesson_progress_before_write();

alter table public.lesson_progress enable row level security;

create policy lesson_progress_select_own on public.lesson_progress
  for select to authenticated
  using (user_id = (select auth.uid()));

create policy lesson_progress_insert_own on public.lesson_progress
  for insert to authenticated
  with check (user_id = (select auth.uid()));

create policy lesson_progress_update_own on public.lesson_progress
  for update to authenticated
  using (user_id = (select auth.uid()))
  with check (user_id = (select auth.uid()));

revoke all on table public.lesson_progress from anon, authenticated;
grant select on table public.lesson_progress to authenticated;
grant insert (lesson_id, user_id, status, completed_section_ids, current_section_id, completed_at)
  on table public.lesson_progress to authenticated;
grant update (status, completed_section_ids, current_section_id, completed_at)
  on table public.lesson_progress to authenticated;
