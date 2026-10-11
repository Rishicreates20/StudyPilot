-- Background jobs, the AI usage ledger and versioned learning roadmaps.
--
-- Who writes what
--   * The API (role `authenticated`, acting as the signed-in learner) may create a job, ask to
--     cancel one, read its own rows, and switch which roadmap version is current.
--   * The worker connects with the privileged database role (no row security), claims jobs,
--     records usage and stores finished roadmaps. Clients therefore need NO insert privilege on
--     roadmaps, and a learner can never write a plan directly.
--
-- Guarantees the database itself enforces, whatever the application does
--   * every row belongs to one user, and children carry the same user_id through composite keys;
--   * at most one queued/running generation per goal; an idempotency key is used once per user;
--   * a job's lock, finish time and error always agree with its status;
--   * one roadmap per job (a retried or double-claimed job cannot store a second plan);
--   * version numbers are unique per goal and at most one version is current;
--   * a stored roadmap's content never changes: clients can update the `status` column only;
--   * deleting a goal removes its jobs and roadmaps.

-- --- generation_jobs ------------------------------------------------------------------------------

create table public.generation_jobs (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.profiles (id) on delete cascade,
  goal_id uuid not null,
  job_type text not null check (job_type in ('roadmap')),
  status text not null default 'queued'
    check (status in ('queued', 'running', 'completed', 'failed', 'cancelled')),
  -- Human-readable position in the pipeline ("planning"), and a 0-100 hint for the progress bar.
  stage text not null default 'queued' check (char_length(stage) between 1 and 40),
  progress integer not null default 0 check (progress between 0 and 100),
  attempts integer not null default 0 check (attempts >= 0),
  max_attempts integer not null default 3 check (max_attempts between 1 and 10),
  run_at timestamptz not null default now(),
  locked_by text check (locked_by is null or char_length(locked_by) <= 100),
  locked_until timestamptz,
  cancel_requested boolean not null default false,
  idempotency_key text
    check (idempotency_key is null or char_length(idempotency_key) between 8 and 128),
  -- What the learner asked for (for example a revision note); the goal itself is read at run time.
  request jsonb not null default '{}'::jsonb check (jsonb_typeof(request) = 'object'),
  -- The validated output of the last finished stage, so a retry does not pay for it twice.
  checkpoint jsonb,
  error_code text check (error_code is null or char_length(error_code) <= 60),
  error_message text check (error_message is null or char_length(error_message) <= 500),
  created_at timestamptz not null default now(),
  started_at timestamptz,
  finished_at timestamptz,
  updated_at timestamptz not null default now(),
  constraint generation_jobs_id_user_id_key unique (id, user_id),
  constraint generation_jobs_goal_fk
    foreign key (goal_id, user_id) references public.learning_goals (id, user_id)
    on delete cascade,
  constraint generation_jobs_lock_matches_status
    check ((status = 'running') = (locked_by is not null)),
  constraint generation_jobs_lock_is_complete
    check ((locked_by is null) = (locked_until is null)),
  constraint generation_jobs_finished_matches_status
    check ((status in ('completed', 'failed', 'cancelled')) = (finished_at is not null)),
  constraint generation_jobs_failed_has_error
    check (status <> 'failed' or error_code is not null)
);

comment on table public.generation_jobs is
  'A queued unit of background work (PostgreSQL-backed queue; claimed with FOR UPDATE SKIP LOCKED).';

-- The worker's claim query and the lease reaper.
create index generation_jobs_claim_idx on public.generation_jobs (run_at, created_at)
  where status = 'queued';
create index generation_jobs_lease_idx on public.generation_jobs (locked_until)
  where status = 'running';
-- A goal's job history, and a learner's recent activity (the daily limit).
create index generation_jobs_goal_idx on public.generation_jobs (goal_id, created_at desc);
create index generation_jobs_user_recent_idx on public.generation_jobs (user_id, created_at desc);

-- One generation at a time per goal: a double click or a second tab cannot start a second one.
create unique index generation_jobs_one_active_per_goal on public.generation_jobs (goal_id, job_type)
  where status in ('queued', 'running');
-- Resubmitting the same form returns the same job.
create unique index generation_jobs_idempotency_idx on public.generation_jobs (user_id, idempotency_key)
  where idempotency_key is not null;

-- Cancelling a job that has not started takes effect immediately; a running job notices the flag
-- between stages. (The learner's UPDATE grant covers cancel_requested only; everything else here
-- is changed by this trigger or by the worker.)
create function public.generation_jobs_before_update()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if new.cancel_requested and not old.cancel_requested and old.status = 'queued' then
    new.status := 'cancelled';
    new.stage := 'cancelled';
    new.finished_at := now();
  end if;
  return new;
end;
$$;

create trigger generation_jobs_cancel
  before update on public.generation_jobs
  for each row execute function public.generation_jobs_before_update();

create trigger generation_jobs_set_updated_at
  before update on public.generation_jobs
  for each row execute function public.set_updated_at();

alter table public.generation_jobs enable row level security;

create policy generation_jobs_select_own on public.generation_jobs
  for select to authenticated
  using (user_id = (select auth.uid()));

create policy generation_jobs_insert_own on public.generation_jobs
  for insert to authenticated
  with check (user_id = (select auth.uid()));

-- Only unfinished jobs can be touched, and the only thing a learner can do is ask for a cancel.
create policy generation_jobs_cancel_own on public.generation_jobs
  for update to authenticated
  using (user_id = (select auth.uid()) and status in ('queued', 'running'))
  with check (user_id = (select auth.uid()) and cancel_requested);

revoke all on table public.generation_jobs from anon, authenticated;
grant select on table public.generation_jobs to authenticated;
grant insert (user_id, goal_id, job_type, idempotency_key, request)
  on table public.generation_jobs to authenticated;
grant update (cancel_requested) on table public.generation_jobs to authenticated;

-- --- ai_usage_events ------------------------------------------------------------------------------

-- One row per model call, written by the worker. Drives cost visibility and the daily limits.
create table public.ai_usage_events (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.profiles (id) on delete cascade,
  job_id uuid not null,
  purpose text not null check (char_length(purpose) between 1 and 60),
  provider text not null check (char_length(provider) between 1 and 40),
  model_id text not null default '' check (char_length(model_id) <= 120),
  prompt_version text not null check (char_length(prompt_version) between 1 and 60),
  input_tokens integer check (input_tokens is null or input_tokens >= 0),
  output_tokens integer check (output_tokens is null or output_tokens >= 0),
  latency_ms integer not null default 0 check (latency_ms >= 0),
  finish_reason text not null default '' check (char_length(finish_reason) <= 60),
  error_code text check (error_code is null or char_length(error_code) <= 60),
  created_at timestamptz not null default now(),
  constraint ai_usage_events_job_fk
    foreign key (job_id, user_id) references public.generation_jobs (id, user_id)
    on delete cascade
);

create index ai_usage_events_job_idx on public.ai_usage_events (job_id);
create index ai_usage_events_user_idx on public.ai_usage_events (user_id, created_at desc);

alter table public.ai_usage_events enable row level security;

create policy ai_usage_events_select_own on public.ai_usage_events
  for select to authenticated
  using (user_id = (select auth.uid()));

revoke all on table public.ai_usage_events from anon, authenticated;
grant select on table public.ai_usage_events to authenticated;

-- --- roadmaps -------------------------------------------------------------------------------------

create table public.roadmaps (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.profiles (id) on delete cascade,
  goal_id uuid not null,
  job_id uuid not null,
  -- 1, 2, 3 ... per goal. A regeneration is a NEW row; earlier versions are kept.
  version integer not null check (version >= 1),
  status text not null default 'current' check (status in ('current', 'superseded')),
  title text not null check (char_length(btrim(title)) between 1 and 200),
  overview text not null check (char_length(overview) between 1 and 4000),
  target_outcome text not null check (char_length(target_outcome) between 1 and 1000),
  language text not null check (language ~ '^[a-z]{2,3}$'),
  -- Where the plan's content comes from. Never "official" unless a real document backs it.
  syllabus_basis text not null
    check (syllabus_basis in ('learner_stated', 'uploaded_document', 'general_knowledge')),
  assumptions text[] not null default '{}'::text[],
  unknowns text[] not null default '{}'::text[],
  -- [{"id": "o1", "text": "..."}]: what the plan promises the learner will be able to do.
  objectives jsonb not null
    check (jsonb_typeof(objectives) = 'array' and jsonb_array_length(objectives) between 1 and 12),
  -- [{"source_id": "...", "chunk_id": "..."}]: only ever the learner's own uploaded material.
  evidence jsonb not null default '[]'::jsonb check (jsonb_typeof(evidence) = 'array'),
  -- Totals computed by the API from the stored items, never taken from the model.
  total_minutes integer not null check (total_minutes >= 5),
  total_days integer not null check (total_days >= 1),
  topic_count integer not null check (topic_count >= 1),
  -- The constraints the plan was made for, kept so an old version is understandable later.
  daily_minutes integer not null check (daily_minutes between 5 and 1440),
  target_date date,
  revision_feedback text check (revision_feedback is null or char_length(revision_feedback) <= 500),
  based_on_roadmap_id uuid,
  prompt_version text not null check (char_length(prompt_version) between 1 and 60),
  provider text not null check (char_length(provider) between 1 and 40),
  model_id text not null check (char_length(model_id) <= 120),
  -- True when a test double produced the content. The UI labels such plans as samples.
  is_synthetic boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  -- Exactly one roadmap per job: a retried or double-claimed job cannot store a second plan.
  constraint roadmaps_job_id_key unique (job_id),
  constraint roadmaps_goal_id_version_key unique (goal_id, version),
  constraint roadmaps_id_user_id_key unique (id, user_id),
  constraint roadmaps_goal_fk
    foreign key (goal_id, user_id) references public.learning_goals (id, user_id)
    on delete cascade,
  constraint roadmaps_job_fk
    foreign key (job_id, user_id) references public.generation_jobs (id, user_id)
    on delete cascade,
  constraint roadmaps_based_on_fk
    foreign key (based_on_roadmap_id, user_id) references public.roadmaps (id, user_id)
    on delete set null (based_on_roadmap_id)
);

comment on table public.roadmaps is
  'A generated, versioned study plan for one goal. Content is immutable; only status changes.';

-- At most one current version per goal.
create unique index roadmaps_one_current_per_goal on public.roadmaps (goal_id)
  where status = 'current';

create trigger roadmaps_set_updated_at
  before update on public.roadmaps
  for each row execute function public.set_updated_at();

-- Switching versions on an archived goal is not allowed (archived goals are read-only).
create function public.roadmaps_before_update()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if exists (
    select 1 from public.learning_goals g where g.id = new.goal_id and g.status = 'archived'
  ) then
    raise exception 'The goal is archived; its roadmap versions are read-only'
      using errcode = '23514', constraint = 'roadmaps_goal_archived_read_only';
  end if;
  return new;
end;
$$;

create trigger roadmaps_goal_not_archived
  before update on public.roadmaps
  for each row execute function public.roadmaps_before_update();

alter table public.roadmaps enable row level security;

create policy roadmaps_select_own on public.roadmaps
  for select to authenticated
  using (user_id = (select auth.uid()));

create policy roadmaps_switch_version_own on public.roadmaps
  for update to authenticated
  using (user_id = (select auth.uid()))
  with check (user_id = (select auth.uid()));

revoke all on table public.roadmaps from anon, authenticated;
grant select on table public.roadmaps to authenticated;
grant update (status) on table public.roadmaps to authenticated;

-- --- roadmap_modules ------------------------------------------------------------------------------

create table public.roadmap_modules (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null,
  roadmap_id uuid not null,
  position integer not null check (position >= 1),
  title text not null check (char_length(btrim(title)) between 1 and 200),
  summary text not null check (char_length(summary) between 1 and 1000),
  constraint roadmap_modules_roadmap_position_key unique (roadmap_id, position),
  constraint roadmap_modules_id_roadmap_key unique (id, roadmap_id),
  constraint roadmap_modules_roadmap_fk
    foreign key (roadmap_id, user_id) references public.roadmaps (id, user_id)
    on delete cascade
);

alter table public.roadmap_modules enable row level security;

create policy roadmap_modules_select_own on public.roadmap_modules
  for select to authenticated
  using (user_id = (select auth.uid()));

revoke all on table public.roadmap_modules from anon, authenticated;
grant select on table public.roadmap_modules to authenticated;

-- --- roadmap_items --------------------------------------------------------------------------------

-- Topics (the core plan), revision sessions (scheduled recall of earlier topics) and optional
-- enrichment (unscheduled extras). `position` orders them for display: topics in study order,
-- then revision sessions by day, then enrichment.
create table public.roadmap_items (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null,
  roadmap_id uuid not null,
  module_id uuid,
  kind text not null check (kind in ('topic', 'revision', 'enrichment')),
  position integer not null check (position >= 1),
  -- Stable, human-readable identifier unique within the roadmap (later lessons and mastery link to it).
  item_key text not null
    check (char_length(item_key) <= 48 and item_key ~ '^[a-z0-9]+(-[a-z0-9]+)*$'),
  title text not null check (char_length(btrim(title)) between 1 and 200),
  -- For a revision session this is the task the learner does.
  description text not null check (char_length(description) between 1 and 1000),
  practice_task text check (practice_task is null or char_length(practice_task) <= 600),
  objective_ids text[] not null default '{}'::text[],
  estimated_minutes integer not null check (estimated_minutes between 5 and 480),
  -- The study day (1 = the day the plan was made). Enrichment is not scheduled.
  day_number integer check (day_number is null or day_number between 1 and 366),
  constraint roadmap_items_roadmap_position_key unique (roadmap_id, position),
  constraint roadmap_items_roadmap_key_key unique (roadmap_id, item_key),
  constraint roadmap_items_id_roadmap_key unique (id, roadmap_id),
  constraint roadmap_items_scheduled_unless_enrichment
    check ((kind = 'enrichment') = (day_number is null)),
  constraint roadmap_items_topics_have_a_module check ((kind = 'topic') = (module_id is not null)),
  constraint roadmap_items_topics_have_practice
    check (kind <> 'topic' or practice_task is not null),
  constraint roadmap_items_roadmap_fk
    foreign key (roadmap_id, user_id) references public.roadmaps (id, user_id)
    on delete cascade,
  constraint roadmap_items_module_fk
    foreign key (module_id, roadmap_id) references public.roadmap_modules (id, roadmap_id)
    on delete cascade
);

create index roadmap_items_module_idx on public.roadmap_items (module_id);

alter table public.roadmap_items enable row level security;

create policy roadmap_items_select_own on public.roadmap_items
  for select to authenticated
  using (user_id = (select auth.uid()));

revoke all on table public.roadmap_items from anon, authenticated;
grant select on table public.roadmap_items to authenticated;

-- --- roadmap_item_prerequisites -------------------------------------------------------------------

-- "Item A must come before item B". For a revision session the prerequisites are the topics it
-- revisits (you cannot revise what you have not yet studied). Both ends must be in the same roadmap.
create table public.roadmap_item_prerequisites (
  item_id uuid not null,
  prerequisite_id uuid not null,
  roadmap_id uuid not null,
  user_id uuid not null,
  primary key (item_id, prerequisite_id),
  constraint roadmap_item_prerequisites_not_self check (item_id <> prerequisite_id),
  constraint roadmap_item_prerequisites_item_fk
    foreign key (item_id, roadmap_id) references public.roadmap_items (id, roadmap_id)
    on delete cascade,
  constraint roadmap_item_prerequisites_prerequisite_fk
    foreign key (prerequisite_id, roadmap_id) references public.roadmap_items (id, roadmap_id)
    on delete cascade,
  constraint roadmap_item_prerequisites_roadmap_fk
    foreign key (roadmap_id, user_id) references public.roadmaps (id, user_id)
    on delete cascade
);

create index roadmap_item_prerequisites_roadmap_idx on public.roadmap_item_prerequisites (roadmap_id);

alter table public.roadmap_item_prerequisites enable row level security;

create policy roadmap_item_prerequisites_select_own on public.roadmap_item_prerequisites
  for select to authenticated
  using (user_id = (select auth.uid()));

revoke all on table public.roadmap_item_prerequisites from anon, authenticated;
grant select on table public.roadmap_item_prerequisites to authenticated;
