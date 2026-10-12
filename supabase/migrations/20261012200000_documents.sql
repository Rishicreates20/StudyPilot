-- Study material the learner uploads or pastes: private files, extracted pages, searchable passages.
--
-- Who writes what
--   * The API (role `authenticated`, acting as the signed-in learner) stores a file in the private
--     `documents` bucket under the learner's own prefix, records the document, queues its
--     processing job, renames it, asks for it to be processed again, and deletes it. It can never
--     write extracted text, passages or vectors, and it cannot mark a document `ready`.
--   * The worker connects with the privileged database role (no row security). It is the only
--     writer of pages (extracted text), passages and their embeddings, and of document status
--     beyond `queued`.
--   * A learner may correct extracted text only while a document waits for their review.
--
-- Guarantees the database itself enforces, whatever the application does
--   * every file lives under `{user_id}/{document_id}/...` in a PRIVATE bucket, and Storage's own
--     row security lets a learner touch only objects under their own `{user_id}/` prefix;
--   * a passage belongs to one document, one goal and one learner at once (composite keys), so a
--     passage can never be attached to someone else's document or goal;
--   * every vector has exactly 1536 numbers (the column type), and every passage records the model
--     that made it;
--   * a document is `ready` only with an index time; `failed` always has an error code; the same
--     file (by SHA-256) is stored once per goal;
--   * archived goals are read-only: no new documents, no re-processing, no edits;
--   * deleting a document, a goal or an account removes its pages and passages. The FILES in
--     Storage are removed by the API when a document or a goal is deleted; a row delete never
--     removes an object, so deleting an account directly in Supabase leaves its `{user_id}/` files
--     until that folder is removed from Storage (see docs/SUPABASE_SETUP.md, retention).

create extension if not exists vector with schema extensions;

-- --- The private bucket and its access rules ----------------------------------------------------
--
-- Supabase's Storage service creates its own tables (`storage.buckets`, `storage.objects`). A fresh
-- local stack started without that service has none yet, so this block applies the bucket and its
-- rules only where Storage is installed (every hosted project), and says so where it is not. A
-- stack without Storage can still run everything else; uploads then need DOCUMENT_STORAGE=local.

do $storage$
begin
  if to_regclass('storage.buckets') is null or to_regclass('storage.objects') is null then
    raise notice 'Supabase Storage is not installed here: the documents bucket and its policies were not created';
    return;
  end if;

  insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
  values (
    'documents', 'documents', false, 10485760,
    array['application/pdf', 'text/plain', 'image/png', 'image/jpeg', 'image/webp']
  )
  on conflict (id) do update
    set public = false,
        file_size_limit = excluded.file_size_limit,
        allowed_mime_types = excluded.allowed_mime_types;

  -- Own prefix only; no update policy, so an object can never be overwritten in place.
  drop policy if exists documents_objects_select_own on storage.objects;
  create policy documents_objects_select_own on storage.objects
    for select to authenticated
    using (bucket_id = 'documents' and (storage.foldername(name))[1] = (select auth.uid())::text);

  drop policy if exists documents_objects_insert_own on storage.objects;
  create policy documents_objects_insert_own on storage.objects
    for insert to authenticated
    with check (bucket_id = 'documents' and (storage.foldername(name))[1] = (select auth.uid())::text);

  drop policy if exists documents_objects_delete_own on storage.objects;
  create policy documents_objects_delete_own on storage.objects
    for delete to authenticated
    using (bucket_id = 'documents' and (storage.foldername(name))[1] = (select auth.uid())::text);
end
$storage$;

-- --- generation_jobs: document jobs -------------------------------------------------------------

alter table public.generation_jobs
  drop constraint generation_jobs_job_type_check;

alter table public.generation_jobs
  add constraint generation_jobs_job_type_check
    check (job_type in ('roadmap', 'lesson', 'quiz', 'grade', 'document'));

-- --- source_documents ---------------------------------------------------------------------------

create table public.source_documents (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.profiles (id) on delete cascade,
  goal_id uuid not null,
  title text not null check (char_length(btrim(title)) between 1 and 200),
  -- What it is, decided from its bytes (never from its name or the browser's claim).
  kind text not null check (kind in ('pdf', 'text', 'image', 'pasted')),
  original_name text check (original_name is null or char_length(original_name) <= 200),
  mime_type text check (mime_type is null or char_length(mime_type) <= 100),
  size_bytes integer not null check (size_bytes between 1 and 52428800),
  sha256 text not null check (sha256 ~ '^[0-9a-f]{64}$'),
  -- {user_id}/{document_id}/{safe name}. Pasted text is stored as a small text file like any
  -- upload, so there is one pipeline and one place a learner's material is kept.
  storage_path text not null,
  -- queued -> processing -> ready, or -> review (extracted text waits for the learner) -> queued
  -- again once they confirm it, or failed with a reason.
  status text not null check (status in ('queued', 'processing', 'review', 'ready', 'failed')),
  error_code text check (error_code is null or char_length(error_code) <= 60),
  -- A sentence a learner may read, from a fixed list of messages: never model or file content.
  error_message text check (error_message is null or char_length(error_message) <= 300),
  -- Real pages (a PDF or an image) or parts of a text: decides how a position is described.
  paginated boolean not null default false,
  page_count integer check (page_count is null or page_count >= 0),
  chunk_count integer not null default 0 check (chunk_count >= 0),
  char_count integer not null default 0 check (char_count >= 0),
  -- Pages read from a picture by a vision model, which the learner should check.
  ocr_page_count integer not null default 0 check (ocr_page_count >= 0),
  -- [{"code": "PAGES_WITHOUT_TEXT", "message": "...", "page": 2}]
  warnings jsonb not null default '[]'::jsonb check (jsonb_typeof(warnings) = 'array'),
  embedding_model text check (embedding_model is null or char_length(embedding_model) <= 100),
  indexed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint source_documents_id_user_id_key unique (id, user_id),
  constraint source_documents_id_goal_user_key unique (id, goal_id, user_id),
  constraint source_documents_goal_fk
    foreign key (goal_id, user_id) references public.learning_goals (id, user_id)
    on delete cascade,
  -- The same file is stored once per goal.
  constraint source_documents_one_copy_per_goal unique (user_id, goal_id, sha256),
  constraint source_documents_path_is_own
    check (storage_path like user_id::text || '/' || id::text || '/%'),
  constraint source_documents_ready_is_indexed check (status <> 'ready' or indexed_at is not null),
  constraint source_documents_failed_has_reason check (status <> 'failed' or error_code is not null)
);

comment on table public.source_documents is
  'A document of study material for one goal. Files are in the private documents bucket.';

create index source_documents_goal_idx on public.source_documents (goal_id, created_at desc);
create index source_documents_user_idx on public.source_documents (user_id);

create trigger source_documents_set_updated_at
  before update on public.source_documents
  for each row execute function public.set_updated_at();

alter table public.source_documents enable row level security;

create policy source_documents_select_own on public.source_documents
  for select to authenticated
  using (user_id = (select auth.uid()));

create policy source_documents_insert_own on public.source_documents
  for insert to authenticated
  with check (user_id = (select auth.uid()));

create policy source_documents_update_own on public.source_documents
  for update to authenticated
  using (user_id = (select auth.uid()))
  with check (user_id = (select auth.uid()));

-- Not while the worker is reading it: the worker would be writing pages for a document that is gone.
create policy source_documents_delete_own on public.source_documents
  for delete to authenticated
  using (user_id = (select auth.uid()) and status <> 'processing');

revoke all on table public.source_documents from anon, authenticated;
grant select on table public.source_documents to authenticated;
grant insert (id, user_id, goal_id, title, kind, original_name, mime_type, size_bytes, sha256,
              storage_path, status)
  on table public.source_documents to authenticated;
grant update (title, status) on table public.source_documents to authenticated;
grant delete on table public.source_documents to authenticated;

-- What a client may do to a document, checked on every write it makes (the worker is exempt:
-- it connects as a different role). Runs as the caller (SECURITY INVOKER).
create function public.source_documents_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  goal_status text;
begin
  if current_user not in ('authenticated', 'anon') then
    return new;
  end if;

  select g.status into goal_status
  from public.learning_goals g
  where g.id = new.goal_id and g.user_id = new.user_id;
  if goal_status = 'archived' then
    raise exception 'An archived goal is read-only: its documents cannot change'
      using errcode = '23514', constraint = 'source_documents_goal_archived';
  end if;

  if tg_op = 'INSERT' then
    if new.status <> 'queued' then
      raise exception 'A new document starts out queued'
        using errcode = '23514', constraint = 'source_documents_client_status';
    end if;
  elsif new.status is distinct from old.status then
    -- A learner can send a document that is waiting, finished or failed to be processed again
    -- (confirming reviewed text is the same move). Every other change of status is the worker's.
    if not (old.status in ('review', 'ready', 'failed') and new.status = 'queued') then
      raise exception 'A document can only be sent to be processed again from review, ready or failed'
        using errcode = '23514', constraint = 'source_documents_client_status';
    end if;
    new.error_code := null;
    new.error_message := null;
  end if;
  return new;
end;
$$;

create trigger source_documents_guard_write
  before insert or update on public.source_documents
  for each row execute function public.source_documents_guard();

-- --- document_pages: the extracted text, page by page -------------------------------------------

create table public.document_pages (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null,
  document_id uuid not null,
  page_number integer not null check (page_number >= 1),
  text text not null check (char_length(text) <= 400000),
  -- text_layer: read from a PDF's own text; ocr: read from a picture by a vision model; text:
  -- from a text file or pasted material.
  source text not null check (source in ('text_layer', 'ocr', 'text')),
  -- Only for ocr pages: how sure the model was. Anything but clear is shown to be checked.
  legibility text check (legibility is null or legibility in ('clear', 'partly', 'poor', 'none')),
  needs_review boolean not null default false,
  edited boolean not null default false,
  created_at timestamptz not null default now(),
  constraint document_pages_document_page_key unique (document_id, page_number),
  constraint document_pages_document_fk
    foreign key (document_id, user_id) references public.source_documents (id, user_id)
    on delete cascade
);

alter table public.document_pages enable row level security;

create policy document_pages_select_own on public.document_pages
  for select to authenticated
  using (user_id = (select auth.uid()));

create policy document_pages_update_own on public.document_pages
  for update to authenticated
  using (user_id = (select auth.uid()))
  with check (user_id = (select auth.uid()));

revoke all on table public.document_pages from anon, authenticated;
grant select on table public.document_pages to authenticated;
grant update (text) on table public.document_pages to authenticated;

-- A learner can correct a page's text only while the document waits for their review, and
-- correcting it marks it as edited and as looked at.
create function public.document_pages_guard()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
  document_status text;
begin
  if current_user not in ('authenticated', 'anon') then
    return new;
  end if;
  select d.status into document_status
  from public.source_documents d
  where d.id = new.document_id and d.user_id = new.user_id;
  if document_status is distinct from 'review' then
    raise exception 'Text can only be corrected while a document waits for review'
      using errcode = '23514', constraint = 'document_pages_not_in_review';
  end if;
  if new.text is distinct from old.text then
    new.edited := true;
    new.needs_review := false;
  end if;
  return new;
end;
$$;

create trigger document_pages_guard_update
  before update on public.document_pages
  for each row execute function public.document_pages_guard();

-- --- document_chunks: the passages that are searched and cited ----------------------------------

create table public.document_chunks (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null,
  goal_id uuid not null,
  document_id uuid not null,
  chunk_index integer not null check (chunk_index >= 0),
  page_start integer not null check (page_start >= 1),
  page_end integer not null,
  section_title text check (section_title is null or char_length(section_title) <= 200),
  content text not null check (char_length(content) between 1 and 8000),
  -- Exactly 1536 numbers, scaled to length 1: the type itself refuses anything else.
  embedding extensions.vector(1536) not null,
  embedding_model text not null check (char_length(embedding_model) between 1 and 100),
  -- Plain 'simple' configuration: no stemming, so it works across English, Hindi and Odia.
  fts tsvector generated always as (to_tsvector('simple'::regconfig, content)) stored,
  created_at timestamptz not null default now(),
  constraint document_chunks_pages_in_order check (page_end >= page_start),
  constraint document_chunks_document_chunk_key unique (document_id, chunk_index),
  constraint document_chunks_id_user_id_key unique (id, user_id),
  constraint document_chunks_document_fk
    foreign key (document_id, goal_id, user_id)
    references public.source_documents (id, goal_id, user_id) on delete cascade
);

comment on column public.document_chunks.embedding is
  'Unit-length vector. Searched exactly within one learner''s goal (see app/retrieval): a shared '
  'ANN index would return too few rows once other learners'' vectors fill its candidate list.';

create index document_chunks_user_goal_idx on public.document_chunks (user_id, goal_id);
create index document_chunks_fts_idx on public.document_chunks using gin (fts);

alter table public.document_chunks enable row level security;

create policy document_chunks_select_own on public.document_chunks
  for select to authenticated
  using (user_id = (select auth.uid()));

revoke all on table public.document_chunks from anon, authenticated;
grant select on table public.document_chunks to authenticated;

-- --- generation_jobs: a document job names its document -----------------------------------------

alter table public.generation_jobs
  add column document_id uuid,
  add constraint generation_jobs_document_fk
    foreign key (document_id, user_id) references public.source_documents (id, user_id)
    on delete cascade,
  add constraint generation_jobs_document_matches_type
    check ((job_type = 'document') = (document_id is not null));

create unique index generation_jobs_one_active_per_document on public.generation_jobs (document_id)
  where status in ('queued', 'running') and document_id is not null;

create index generation_jobs_document_idx on public.generation_jobs (document_id, created_at desc)
  where document_id is not null;

grant insert (document_id) on table public.generation_jobs to authenticated;

-- Replaces the check of the previous migration (lesson and quiz jobs) and adds the document rule:
-- a document job names a document of the SAME goal and learner. Runs as the caller (SECURITY
-- INVOKER), who can only see their own rows, which is exactly the check wanted.
create or replace function public.generation_jobs_before_insert()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if new.job_type in ('lesson', 'quiz') and not exists (
    select 1
    from public.roadmap_items i
    join public.roadmaps r on r.id = i.roadmap_id and r.user_id = i.user_id
    where i.id = new.item_id
      and i.user_id = new.user_id
      and r.goal_id = new.goal_id
      and r.status = 'current'
      and i.kind <> 'revision'
  ) then
    raise exception 'A lesson or quiz job must name a topic of the goal''s current roadmap'
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
