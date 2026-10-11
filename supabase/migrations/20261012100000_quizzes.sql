-- Quizzes, attempts, graded answers and topic mastery.
--
-- Who writes what
--   * The API (role `authenticated`, acting as the signed-in learner) may queue a QUIZ job for a
--     topic of its current roadmap that already has a lesson, and read its own quizzes, questions,
--     attempts, answers and mastery. It can write NONE of the assessment tables.
--   * The worker writes quizzes, questions and answer keys (the writer of a quiz) and grades
--     short answers. A small privileged grader (app/grading) is the only code that reads an answer
--     key, and only to grade the attempt it was handed; it writes attempts, answers and mastery.
--
-- Guarantees the database itself enforces, whatever the application does
--   * `question_answer_keys` has row security on and NO policy and NO privilege for browser-facing
--     roles: a correct answer or an explanation can never be read, or guessed at, through the
--     Data API, before or after a submission (feedback is copied into the learner's own answer row
--     when it is graded);
--   * a quiz can be attempted once (unique `quiz_id`); a submission key is used once per learner;
--     one answer per question per attempt;
--   * points, correctness and mastery cannot be written by a client: they have no write privilege;
--   * a graded attempt always has its score; a grading job always points at its attempt;
--   * deleting a goal removes its quizzes, attempts, answers and mastery.

-- --- generation_jobs: quiz and grading jobs -------------------------------------------------------

alter table public.generation_jobs
  drop constraint generation_jobs_job_type_check,
  drop constraint generation_jobs_item_matches_type;

alter table public.generation_jobs
  add constraint generation_jobs_job_type_check
    check (job_type in ('roadmap', 'lesson', 'quiz', 'grade')),
  -- The attempt a grading job grades; null for every other kind of job.
  add column attempt_id uuid,
  add constraint generation_jobs_item_matches_type
    check ((job_type in ('lesson', 'quiz')) = (item_id is not null)),
  add constraint generation_jobs_attempt_matches_type
    check ((job_type = 'grade') = (attempt_id is not null));

-- One lesson and one quiz may be in progress for a topic, but not two of the same kind.
drop index public.generation_jobs_one_active_per_item;

create unique index generation_jobs_one_active_per_item on public.generation_jobs (item_id, job_type)
  where status in ('queued', 'running') and item_id is not null;

create unique index generation_jobs_one_active_per_attempt on public.generation_jobs (attempt_id)
  where status in ('queued', 'running') and attempt_id is not null;

-- --- quizzes --------------------------------------------------------------------------------------

create table public.quizzes (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.profiles (id) on delete cascade,
  roadmap_id uuid not null,
  item_id uuid not null,
  -- The lesson version the questions were written from.
  lesson_id uuid not null,
  job_id uuid not null,
  -- `check` tests the topic; `practice` was written to target the learner's weakest objectives.
  purpose text not null check (purpose in ('check', 'practice')),
  focus_objective_ids text[] not null default '{}'::text[],
  title text not null check (char_length(btrim(title)) between 1 and 200),
  language text not null check (language ~ '^[a-z]{2,3}$'),
  question_count integer not null check (question_count between 1 and 12),
  prompt_version text not null check (char_length(prompt_version) between 1 and 60),
  provider text not null check (char_length(provider) between 1 and 40),
  model_id text not null check (char_length(model_id) <= 120),
  -- True when a test double produced the questions. The UI labels such quizzes as samples.
  is_synthetic boolean not null default false,
  created_at timestamptz not null default now(),
  constraint quizzes_job_id_key unique (job_id),
  constraint quizzes_id_user_id_key unique (id, user_id),
  constraint quizzes_roadmap_fk
    foreign key (roadmap_id, user_id) references public.roadmaps (id, user_id) on delete cascade,
  constraint quizzes_item_fk
    foreign key (item_id, roadmap_id) references public.roadmap_items (id, roadmap_id)
    on delete cascade,
  constraint quizzes_lesson_fk
    foreign key (lesson_id, user_id) references public.lessons (id, user_id) on delete cascade,
  constraint quizzes_job_fk
    foreign key (job_id, user_id) references public.generation_jobs (id, user_id)
    on delete cascade
);

comment on table public.quizzes is
  'A generated quiz for one roadmap topic. Immutable; the worker is the only writer.';

create index quizzes_item_idx on public.quizzes (item_id, created_at desc);

alter table public.quizzes enable row level security;

create policy quizzes_select_own on public.quizzes
  for select to authenticated
  using (user_id = (select auth.uid()));

revoke all on table public.quizzes from anon, authenticated;
grant select on table public.quizzes to authenticated;

-- --- questions (what the learner may see: never the answer) -------------------------------------

create table public.questions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null,
  quiz_id uuid not null,
  position integer not null check (position >= 1),
  kind text not null check (kind in ('multiple_choice', 'true_false', 'short_answer')),
  prompt text not null check (char_length(btrim(prompt)) between 5 and 1500),
  -- [{"id": "a", "text": "..."}]; null for a short-answer question. Which one is right is NOT here.
  options jsonb,
  -- The roadmap objective this question tests (an id from the roadmap's objectives).
  objective_id text not null check (char_length(objective_id) between 1 and 20),
  difficulty text not null check (difficulty in ('easy', 'medium', 'hard')),
  -- What the question is worth: 1 easy, 2 medium, 3 hard. Also its weight in mastery.
  max_points integer not null check (max_points between 1 and 3),
  constraint questions_quiz_position_key unique (quiz_id, position),
  constraint questions_id_user_id_key unique (id, user_id),
  constraint questions_options_match_kind check (
    (kind = 'short_answer' and options is null)
    or (kind <> 'short_answer' and options is not null and jsonb_typeof(options) = 'array'
        and jsonb_array_length(options) between 2 and 6)
  ),
  constraint questions_quiz_fk
    foreign key (quiz_id, user_id) references public.quizzes (id, user_id) on delete cascade
);

alter table public.questions enable row level security;

create policy questions_select_own on public.questions
  for select to authenticated
  using (user_id = (select auth.uid()));

revoke all on table public.questions from anon, authenticated;
grant select on table public.questions to authenticated;

-- --- question_answer_keys (the answer, the explanation, the rubric: server side only) -------------

create table public.question_answer_keys (
  question_id uuid primary key,
  user_id uuid not null,
  -- Multiple choice and true/false: the id of the right option.
  correct_option_id text,
  -- Short answer: {"points": [{"id": "p1", "text": "...", "points": 1}]}, and a model answer.
  rubric jsonb,
  model_answer text,
  explanation text not null check (char_length(btrim(explanation)) between 1 and 2000),
  -- {"a": "why this option is right or wrong", ...}
  option_notes jsonb not null default '{}'::jsonb,
  constraint question_answer_keys_one_kind
    check ((correct_option_id is not null) <> (rubric is not null)),
  constraint question_answer_keys_question_fk
    foreign key (question_id, user_id) references public.questions (id, user_id)
    on delete cascade
);

comment on table public.question_answer_keys is
  'Answers and explanations. No policy and no grant for any client role: only the grader reads it.';

-- Row security with NO policy and NO privilege: a browser-facing role can neither see nor guess.
alter table public.question_answer_keys enable row level security;
revoke all on table public.question_answer_keys from anon, authenticated;

-- --- quiz_attempts --------------------------------------------------------------------------------

create table public.quiz_attempts (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null,
  quiz_id uuid not null,
  -- `grading` while a short answer waits for the grader; `graded` once every answer has a result.
  status text not null check (status in ('grading', 'graded')),
  -- The same key submitted twice returns the same attempt.
  idempotency_key text
    check (idempotency_key is null or char_length(idempotency_key) between 8 and 128),
  submitted_at timestamptz not null default now(),
  graded_at timestamptz,
  points_earned numeric(6, 2) check (points_earned is null or points_earned >= 0),
  points_possible integer check (points_possible is null or points_possible >= 1),
  percent numeric(5, 2) check (percent is null or percent between 0 and 100),
  -- A quiz is attempted once. Practising again means a new quiz with new questions.
  constraint quiz_attempts_quiz_id_key unique (quiz_id),
  constraint quiz_attempts_id_user_id_key unique (id, user_id),
  constraint quiz_attempts_graded_has_score
    check ((status = 'graded') = (graded_at is not null and percent is not null)),
  constraint quiz_attempts_quiz_fk
    foreign key (quiz_id, user_id) references public.quizzes (id, user_id) on delete cascade
);

create unique index quiz_attempts_idempotency_idx on public.quiz_attempts (user_id, idempotency_key)
  where idempotency_key is not null;
create index quiz_attempts_user_idx on public.quiz_attempts (user_id, submitted_at desc);

alter table public.quiz_attempts enable row level security;

create policy quiz_attempts_select_own on public.quiz_attempts
  for select to authenticated
  using (user_id = (select auth.uid()));

revoke all on table public.quiz_attempts from anon, authenticated;
grant select on table public.quiz_attempts to authenticated;

-- A grading job points at its attempt (deleting the attempt, or the goal, removes the job).
alter table public.generation_jobs
  add constraint generation_jobs_attempt_fk
    foreign key (attempt_id, user_id) references public.quiz_attempts (id, user_id)
    on delete cascade;

-- --- quiz_answers ---------------------------------------------------------------------------------

create table public.quiz_answers (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null,
  attempt_id uuid not null,
  question_id uuid not null,
  -- {"option_id": "b"} or {"text": "..."}; {} when the question was skipped. The learner's own words.
  answer jsonb not null check (jsonb_typeof(answer) = 'object'),
  skipped boolean not null default false,
  -- How the points were decided: by code, by a model against the rubric (an estimate), by the
  -- learner reviewing it, or not yet.
  grading_method text not null
    check (grading_method in ('deterministic', 'ai_estimate', 'self_review', 'pending')),
  is_correct boolean,
  points_awarded numeric(5, 2) check (points_awarded is null or points_awarded >= 0),
  max_points integer not null check (max_points between 1 and 3),
  -- What the learner is shown once graded: the right answer, the explanation, per-option notes,
  -- the rubric and which of its points were met. Copied from the key at grading time.
  feedback jsonb not null check (jsonb_typeof(feedback) = 'object'),
  graded_at timestamptz,
  constraint quiz_answers_attempt_question_key unique (attempt_id, question_id),
  constraint quiz_answers_id_user_id_key unique (id, user_id),
  constraint quiz_answers_pending_has_no_points
    check ((grading_method = 'pending') = (points_awarded is null)),
  constraint quiz_answers_points_within_max check (points_awarded is null or points_awarded <= max_points),
  constraint quiz_answers_attempt_fk
    foreign key (attempt_id, user_id) references public.quiz_attempts (id, user_id)
    on delete cascade,
  constraint quiz_answers_question_fk
    foreign key (question_id, user_id) references public.questions (id, user_id)
    on delete cascade
);

create index quiz_answers_attempt_idx on public.quiz_answers (attempt_id);
create index quiz_answers_question_idx on public.quiz_answers (question_id);

alter table public.quiz_answers enable row level security;

create policy quiz_answers_select_own on public.quiz_answers
  for select to authenticated
  using (user_id = (select auth.uid()));

revoke all on table public.quiz_answers from anon, authenticated;
grant select on table public.quiz_answers to authenticated;

-- --- topic_mastery ------------------------------------------------------------------------------

-- One row per topic: a cache of the transparent score computed from the stored answers, so the
-- scoring method can change and be recomputed without losing anything.
create table public.topic_mastery (
  item_id uuid primary key,
  user_id uuid not null,
  roadmap_id uuid not null,
  score numeric(5, 2) not null check (score between 0 and 100),
  band text not null check (band in ('needs_practice', 'progressing', 'mastered')),
  attempts_count integer not null check (attempts_count >= 1),
  answers_count integer not null check (answers_count >= 1),
  -- Too little evidence to be sure (a single short quiz).
  low_confidence boolean not null,
  -- [{"id": "o1", "score": 62.5, "answers": 3}]
  objectives jsonb not null default '[]'::jsonb check (jsonb_typeof(objectives) = 'array'),
  algorithm_version text not null check (char_length(algorithm_version) between 1 and 40),
  computed_at timestamptz not null default now(),
  constraint topic_mastery_item_fk
    foreign key (item_id, roadmap_id) references public.roadmap_items (id, roadmap_id)
    on delete cascade,
  constraint topic_mastery_roadmap_fk
    foreign key (roadmap_id, user_id) references public.roadmaps (id, user_id) on delete cascade
);

create index topic_mastery_roadmap_idx on public.topic_mastery (roadmap_id);

alter table public.topic_mastery enable row level security;

create policy topic_mastery_select_own on public.topic_mastery
  for select to authenticated
  using (user_id = (select auth.uid()));

revoke all on table public.topic_mastery from anon, authenticated;
grant select on table public.topic_mastery to authenticated;

-- --- generation_jobs: a quiz job must name a topic that already has a lesson ----------------------

-- Replaces the lesson-only check of the previous migration. Runs as the caller (SECURITY INVOKER).
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
  return new;
end;
$$;
