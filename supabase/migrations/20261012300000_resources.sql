-- RECOVERED FILE. This migration was applied to the hosted StudyPilot project (version
-- 20261012300000) but was never committed. It was exported on 2026-10-23 from that project's
-- supabase_migrations.schema_migrations history so the repository matches the database. The code
-- that uses these tables (the YouTube curator, milestone 7) is not in this repository yet.
--
-- Study videos suggested for a roadmap topic, found with the official YouTube Data API.
--
-- Who writes what
--   * The API (role `authenticated`, acting as the signed-in learner) may queue a RESOURCES job for
--     a topic of its current roadmap, and read its own searches and suggested videos. It can write
--     NONE of the resource tables: a learner cannot add, edit or remove a suggestion.
--   * The worker runs the search (and the cheap re-check of links), and is the only writer of
--     `resource_searches`, `topic_resources` and the quota ledger.
--
-- Guarantees the database itself enforces, whatever the application does
--   * every suggestion is a real YouTube video id of 11 characters and its URL is exactly the watch
--     address of that id, so a stored link can never point somewhere else than the id it carries;
--   * a topic has at most one stored search (a new search replaces the old one in one transaction),
--     and a video appears once in it;
--   * the relevance score is 0..100, a language is only recorded together with how it is known,
--     and every suggestion carries the time its details were last confirmed with the API;
--   * `youtube_quota_usage` (the ledger of API units spent, shared by the whole server) has row
--     security on and NO policy and NO privilege for browser-facing roles;
--   * deleting a goal (or a topic's roadmap) removes its searches and suggestions.

-- --- generation_jobs: resource jobs --------------------------------------------------------------

alter table public.generation_jobs
  drop constraint generation_jobs_job_type_check,
  drop constraint generation_jobs_item_matches_type;

alter table public.generation_jobs
  add constraint generation_jobs_job_type_check
    check (job_type in ('roadmap', 'lesson', 'quiz', 'grade', 'document', 'resources')),
  add constraint generation_jobs_item_matches_type
    check ((job_type in ('lesson', 'quiz', 'resources')) = (item_id is not null));

-- Replaces the check of the previous migrations and adds the resources rule: a resources job names
-- a (non-revision) topic of the goal's current roadmap. Runs as the caller (SECURITY INVOKER), who
-- can only see their own rows, which is exactly the check wanted.
create or replace function public.generation_jobs_before_insert()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if new.job_type in ('lesson', 'quiz', 'resources') and not exists (
    select 1
    from public.roadmap_items i
    join public.roadmaps r on r.id = i.roadmap_id and r.user_id = i.user_id
    where i.id = new.item_id
      and i.user_id = new.user_id
      and r.goal_id = new.goal_id
      and r.status = 'current'
      and i.kind <> 'revision'
  ) then
    raise exception 'A lesson, quiz or resources job must name a topic of the goal''s current roadmap'
      using errcode = '23514', constraint = 'generation_jobs_lesson_target';
  end if;
  if new.job_type = 'quiz' and not exists (
    select 1 from public.lessons l
    where l.item_id = new.item_id and l.user_id = new.user_id and l.status = 'current'
  ) then
    raise exception 'A quiz is written from a lesson: the topic has none yet'
      using errcode = '23514', constraint = 'generation_jobs_quiz_needs_lesson';
  end if;
  if new.job_type = 'document' and not exists (
    select 1 from public.source_documents d
    where d.id = new.document_id and d.user_id = new.user_id and d.goal_id = new.goal_id
  ) then
    raise exception 'A document job must name a document of the same goal'
      using errcode = '23514', constraint = 'generation_jobs_document_target';
  end if;
  return new;
end;
$$;

-- --- resource_searches: what was searched for a topic, and when ---------------------------------

create table public.resource_searches (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.profiles (id) on delete cascade,
  roadmap_id uuid not null,
  item_id uuid not null,
  job_id uuid,
  provider text not null check (provider in ('youtube')),
  -- The language codes searched, in the order searched (for example {en,hi}).
  languages text[] not null check (cardinality(languages) between 1 and 6),
  -- The words sent to the provider, kept so a learner (and a developer) can see what was asked.
  queries text[] not null,
  -- How many distinct videos the provider returned, and how many were kept after the checks.
  candidates_seen integer not null check (candidates_seen >= 0),
  result_count integer not null check (result_count >= 0),
  -- API units this search spent (a search costs 100, a details lookup 1).
  units_spent integer not null check (units_spent >= 0),
  searched_at timestamptz not null default now(),
  -- When the stored videos' details were last confirmed with the API (a search confirms them all).
  last_verified_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  constraint resource_searches_one_per_topic unique (item_id),
  constraint resource_searches_id_user_id_key unique (id, user_id),
  constraint resource_searches_item_fk
    foreign key (item_id, user_id) references public.roadmap_items (id, user_id) on delete cascade,
  constraint resource_searches_job_fk
    foreign key (job_id, user_id) references public.generation_jobs (id, user_id)
    on delete cascade
);

create index resource_searches_user_idx on public.resource_searches (user_id, searched_at desc);

-- The worker deletes searches nobody has confirmed with YouTube for 30 days (its developer policies).
create index resource_searches_verified_idx on public.resource_searches (last_verified_at);

alter table public.resource_searches enable row level security;

create policy resource_searches_select_own on public.resource_searches
  for select to authenticated
  using (user_id = (select auth.uid()));

revoke all on table public.resource_searches from anon, authenticated;

grant select on table public.resource_searches to authenticated;

-- --- topic_resources: the suggested videos ------------------------------------------------------

create table public.topic_resources (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null,
  search_id uuid not null,
  item_id uuid not null,
  provider text not null check (provider in ('youtube')),
  -- The provider's own id for the video (a YouTube video id is 11 URL-safe characters).
  external_id text not null check (external_id ~ '^[A-Za-z0-9_-]{11}$'),
  title text not null check (char_length(btrim(title)) between 1 and 300),
  description text not null default '' check (char_length(description) <= 1000),
  channel_id text check (channel_id is null or char_length(channel_id) <= 64),
  channel_title text not null default '' check (char_length(channel_title) <= 200),
  -- Always the watch address of `external_id`: never anything the provider (or a bug) supplied.
  url text not null,
  -- The language the VIDEO declares (YouTube's audio language, else its metadata language), as a
  -- BCP-47 tag; null when it declares none. `language_source` says which field it came from, so
  -- a language is never shown as known when the metadata does not say it.
  language text check (language is null or char_length(language) between 2 and 16),
  language_source text not null check (language_source in ('audio', 'metadata', 'unknown')),
  -- The language searched for when this video was found (what it was a result FOR).
  searched_language text not null check (char_length(searched_language) between 2 and 8),
  published_at timestamptz,
  duration_seconds integer check (duration_seconds is null or duration_seconds >= 0),
  thumbnail_url text check (thumbnail_url is null or thumbnail_url ~ '^https://[A-Za-z0-9.-]+/'),
  thumbnail_width integer check (thumbnail_width is null or thumbnail_width > 0),
  thumbnail_height integer check (thumbnail_height is null or thumbnail_height > 0),
  category_id text check (category_id is null or char_length(category_id) <= 8),
  view_count bigint check (view_count is null or view_count >= 0),
  -- A match estimate from the metadata (title, description, category, length), 0..100. Not a
  -- quality rating. `score_basis` lists the signals it was built from, so it can be explained.
  relevance_score integer not null check (relevance_score between 0 and 100),
  score_basis jsonb not null default '{}'::jsonb check (jsonb_typeof(score_basis) = 'object'),
  position integer not null check (position >= 1),
  -- `unavailable`: a later check found the video private, removed or no longer playable.
  status text not null default 'available' check (status in ('available', 'unavailable')),
  last_verified_at timestamptz not null,
  created_at timestamptz not null default now(),
  constraint topic_resources_url_is_the_watch_address
    check (provider <> 'youtube' or url = 'https://www.youtube.com/watch?v=' || external_id),
  constraint topic_resources_language_has_source
    check ((language is null) = (language_source = 'unknown')),
  constraint topic_resources_video_once_per_search unique (search_id, external_id),
  constraint topic_resources_search_fk
    foreign key (search_id, user_id) references public.resource_searches (id, user_id)
    on delete cascade,
  constraint topic_resources_item_fk
    foreign key (item_id, user_id) references public.roadmap_items (id, user_id) on delete cascade
);

create index topic_resources_item_idx on public.topic_resources (item_id, position);

alter table public.topic_resources enable row level security;

create policy topic_resources_select_own on public.topic_resources
  for select to authenticated
  using (user_id = (select auth.uid()));

revoke all on table public.topic_resources from anon, authenticated;

grant select on table public.topic_resources to authenticated;

-- --- youtube_quota_usage: the API units this server has spent --------------------------------------
-- The YouTube quota belongs to the Google Cloud project behind the API key, not to a learner, so
-- the ledger has no user. It resets at midnight Pacific Time (America/Los_Angeles), which is how
-- YouTube resets its own daily quota, so `day` is the Pacific date. The worker supplies it (it owns
-- the time zone data), so nothing here depends on the database server having one.

create table public.youtube_quota_usage (
  id bigint generated always as identity primary key,
  day date not null,
  endpoint text not null check (endpoint in ('search.list', 'videos.list')),
  units integer not null check (units between 0 and 10000),
  created_at timestamptz not null default now()
);

create index youtube_quota_usage_day_idx on public.youtube_quota_usage (day);

alter table public.youtube_quota_usage enable row level security;

-- No policy and no grant: only the worker's privileged connection reads or writes the ledger.
revoke all on table public.youtube_quota_usage from anon, authenticated;
