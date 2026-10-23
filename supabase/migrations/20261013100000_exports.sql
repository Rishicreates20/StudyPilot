-- RECOVERED FILE. This migration was applied to the hosted StudyPilot project (version
-- 20261013100000) but was never committed. It was exported on 2026-10-23 from that project's
-- supabase_migrations.schema_migrations history so the repository matches the database. The code
-- that uses this table (exports, milestone 8) is not in this repository yet, and the ADR-049 it
-- cites does not exist in docs/ARCHITECTURE.md.
--
-- Exported study files: PDF notes, revision sheets and roadmaps, and PowerPoint slides (ADR-049).
--
-- Who writes what
--   * The API (role `authenticated`, acting as the signed-in learner) may ask for an export of one
--     of its own lessons or roadmap versions, queue the EXPORT job that makes it, read its exports
--     and delete one. It can write none of a file's details: whether an export is ready, where its
--     file is and what it weighs are written only by the worker.
--   * The worker renders the file, stores it in the private `exports` bucket through a one-object
--     signed upload link the API made with the learner's own token (the service-role key is never
--     used), and records it in the same transaction that completes the job.
--
-- Guarantees the database itself enforces, whatever the application does
--   * an export is of exactly one source, a lesson or a roadmap version of the same learner, its
--     format fits that source, and its goal is the source's goal (set here, never by a client);
--   * one export per source, format and template version: asking again finds the same export
--     (sources are immutable versions, so the file would be the same);
--   * a ready export has every file detail and a path under `{user_id}/{export_id}/`; one that is
--     not ready has none;
--   * at most one queued or running job per export;
--   * deleting a lesson, a roadmap, a goal or an account removes the rows. FILES are removed by the
--     API (an export's own, or every export of a goal being deleted), as for documents.

-- --- exports ------------------------------------------------------------------------------------

create table public.exports (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.profiles (id) on delete cascade,
  -- Copied from the source by the trigger below; a client cannot choose it.
  goal_id uuid not null,
  lesson_id uuid,
  roadmap_id uuid,
  format text not null
    check (format in ('notes_pdf', 'revision_pdf', 'roadmap_pdf', 'slides_pptx')),
  -- The templates' version: a new layout makes new exports instead of reusing the old files.
  template_version text not null check (template_version ~ '^[a-z0-9._/-]{1,40}$'),
  -- Written by the worker once the file is stored; all set together, or none.
  storage_path text check (storage_path is null or char_length(storage_path) <= 300),
  -- Short-lived capability used only by the worker; column-level grants keep it out of Data API reads.
  upload_token text check (upload_token is null or char_length(upload_token) <= 1000),
  file_name text check (file_name is null or file_name ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$'),
  content_type text check (content_type is null or content_type in (
    'application/pdf',
    'application/vnd.openxmlformats-officedocument.presentationml.presentation'
  )),
  size_bytes integer check (size_bytes is null or size_bytes > 0),
  sha256 text check (sha256 is null or sha256 ~ '^[0-9a-f]{64}$'),
  -- Pages of a PDF, or slides of a presentation.
  page_count integer check (page_count is null or page_count > 0),
  -- Characters no embedded font could show (printed as a replacement mark); 0 when none.
  unsupported_characters integer check (unsupported_characters is null or unsupported_characters >= 0),
  ready_at timestamptz,
  created_at timestamptz not null default now(),
  constraint exports_id_user_id_key unique (id, user_id),
  constraint exports_goal_fk
    foreign key (goal_id, user_id) references public.learning_goals (id, user_id) on delete cascade,
  constraint exports_lesson_fk
    foreign key (lesson_id, user_id) references public.lessons (id, user_id) on delete cascade,
  constraint exports_roadmap_fk
    foreign key (roadmap_id, user_id) references public.roadmaps (id, user_id) on delete cascade,
  constraint exports_one_source check (num_nonnulls(lesson_id, roadmap_id) = 1),
  constraint exports_format_fits_source check (
    case when lesson_id is not null then format in ('notes_pdf', 'revision_pdf', 'slides_pptx')
         else format in ('roadmap_pdf', 'slides_pptx') end
  ),
  constraint exports_file_details_together check (
    num_nulls(ready_at, storage_path, file_name, content_type, size_bytes, sha256, page_count,
              unsupported_characters) in (0, 8)
  ),
  constraint exports_file_under_own_prefix check (
    storage_path is null or starts_with(storage_path, user_id::text || '/' || id::text || '/')
  ),
  constraint exports_type_fits_format check (
    content_type is null or (content_type = 'application/pdf') = (format <> 'slides_pptx')
  )
);

comment on table public.exports is
  'A downloadable file made from one lesson or roadmap version. Files are in the private exports bucket.';

create unique index exports_one_per_lesson on public.exports (lesson_id, format, template_version)
  where lesson_id is not null;

create unique index exports_one_per_roadmap on public.exports (roadmap_id, format, template_version)
  where roadmap_id is not null;

create index exports_goal_idx on public.exports (goal_id);

-- The goal is always the source's own. Runs as the caller (SECURITY INVOKER), who can only see
-- their own lessons and roadmaps: anyone else's source leaves the goal empty and is refused.
create function public.exports_before_insert()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if new.lesson_id is not null then
    select r.goal_id into new.goal_id
    from public.lessons l
    join public.roadmaps r on r.id = l.roadmap_id and r.user_id = l.user_id
    where l.id = new.lesson_id and l.user_id = new.user_id;
  else
    select r.goal_id into new.goal_id
    from public.roadmaps r
    where r.id = new.roadmap_id and r.user_id = new.user_id;
  end if;
  return new;
end;
$$;

create trigger exports_set_goal
  before insert on public.exports
  for each row execute function public.exports_before_insert();

alter table public.exports enable row level security;

create policy exports_select_own on public.exports
  for select to authenticated
  using (user_id = (select auth.uid()));

create policy exports_insert_own on public.exports
  for insert to authenticated
  with check (user_id = (select auth.uid()));

create policy exports_delete_own on public.exports
  for delete to authenticated
  using (user_id = (select auth.uid()));

create policy exports_upload_token_own on public.exports
  for update to authenticated
  using (user_id = (select auth.uid()) and ready_at is null)
  with check (user_id = (select auth.uid()) and ready_at is null);

revoke all on table public.exports from anon, authenticated;

grant select (id, user_id, goal_id, lesson_id, roadmap_id, format, template_version,
  storage_path, file_name, content_type, size_bytes, sha256, page_count,
  unsupported_characters, ready_at, created_at) on table public.exports to authenticated;

grant delete on table public.exports to authenticated;

grant insert (user_id, lesson_id, roadmap_id, format, template_version, upload_token)
  on table public.exports to authenticated;

grant update (upload_token) on table public.exports to authenticated;

-- --- generation_jobs: export jobs ---------------------------------------------------------------

alter table public.generation_jobs
  add column export_id uuid,
  drop constraint generation_jobs_job_type_check;

alter table public.generation_jobs
  add constraint generation_jobs_job_type_check
    check (job_type in ('roadmap', 'lesson', 'quiz', 'grade', 'document', 'resources', 'export')),
  add constraint generation_jobs_export_matches_type
    check ((job_type = 'export') = (export_id is not null)),
  add constraint generation_jobs_export_fk
    foreign key (export_id, user_id) references public.exports (id, user_id) on delete cascade;

create unique index generation_jobs_one_active_per_export on public.generation_jobs (export_id)
  where status in ('queued', 'running') and export_id is not null;

create index generation_jobs_export_idx on public.generation_jobs (export_id, created_at desc)
  where export_id is not null;

grant insert (export_id) on table public.generation_jobs to authenticated;

-- Replaces the check of the previous migrations and adds the export rule: an export job belongs to
-- the goal of the export it makes.
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
  if new.job_type = 'export' and not exists (
    select 1 from public.exports e
    where e.id = new.export_id and e.user_id = new.user_id and e.goal_id = new.goal_id
  ) then
    raise exception 'An export job must name an export of the same goal'
      using errcode = '23514', constraint = 'generation_jobs_export_target';
  end if;
  return new;
end;
$$;

-- --- The private bucket and its access rules ----------------------------------------------------
-- As for documents: applied only where Supabase Storage is installed. A learner may touch objects
-- under their own `{user_id}/` prefix only. Unlike documents, an export's object may be replaced
-- (`update`): a job that is retried uploads to the same path again, so an export never leaves a
-- second file behind.

do $storage$
begin
  if to_regclass('storage.buckets') is null or to_regclass('storage.objects') is null then
    raise notice 'Supabase Storage is not installed here: the exports bucket and its policies were not created';
    return;
  end if;

  insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
  values (
    'exports', 'exports', false, 26214400,
    array['application/pdf', 'application/vnd.openxmlformats-officedocument.presentationml.presentation']
  )
  on conflict (id) do update
    set public = false,
        file_size_limit = excluded.file_size_limit,
        allowed_mime_types = excluded.allowed_mime_types;

  drop policy if exists exports_objects_select_own on storage.objects;
  create policy exports_objects_select_own on storage.objects
    for select to authenticated
    using (bucket_id = 'exports' and (storage.foldername(name))[1] = (select auth.uid())::text);

  drop policy if exists exports_objects_insert_own on storage.objects;
  create policy exports_objects_insert_own on storage.objects
    for insert to authenticated
    with check (bucket_id = 'exports' and (storage.foldername(name))[1] = (select auth.uid())::text);

  drop policy if exists exports_objects_update_own on storage.objects;
  create policy exports_objects_update_own on storage.objects
    for update to authenticated
    using (bucket_id = 'exports' and (storage.foldername(name))[1] = (select auth.uid())::text)
    with check (bucket_id = 'exports' and (storage.foldername(name))[1] = (select auth.uid())::text);

  drop policy if exists exports_objects_delete_own on storage.objects;
  create policy exports_objects_delete_own on storage.objects
    for delete to authenticated
    using (bucket_id = 'exports' and (storage.foldername(name))[1] = (select auth.uid())::text);
end
$storage$;
