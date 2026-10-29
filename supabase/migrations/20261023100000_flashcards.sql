-- Flashcards and their review history (milestone 7, ADR-050).
--
-- Who writes what
--   * A learner writes their OWN cards (front, back, optionally which roadmap topic they belong to)
--     and their own schedule, and appends to their own review history, all through the API's request
--     transaction as the `authenticated` role. Nothing here is graded, shared or used to measure
--     anyone else, so a learner who edits their own due date only changes their own queue. The API
--     computes every schedule change with the pure scheduler in `app/learning/scheduling.py`.
--   * The worker does not touch these tables.
--
-- Guarantees the database itself enforces, whatever the application does
--   * a card belongs to one goal of the same learner, and a topic it names is a topic of that goal
--     (a roadmap item of one of the goal's own roadmaps);
--   * the schedule is bounded: an interval of 0..365 days, an ease factor of 1.30..3.50;
--   * review history is append-only: a learner can add a review and read their reviews, never
--     change or delete one (it goes only when its card or goal is deleted);
--   * a review records the schedule before and after and the scheduler's version, so the algorithm
--     can be replaced later and old history replayed;
--   * the same Idempotency-Key on the same card is one review;
--   * deleting a goal (or an account) removes its cards and their history.

-- --- flashcards ------------------------------------------------------------------------------------

create table public.flashcards (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.profiles (id) on delete cascade,
  goal_id uuid not null,
  -- The roadmap topic this card is about; optional.
  item_id uuid,
  -- Where the card came from. Only `manual` exists today; later slices add derived cards.
  origin text not null default 'manual' check (origin in ('manual')),
  front text not null check (char_length(btrim(front)) between 1 and 1000),
  back text not null check (char_length(btrim(back)) between 1 and 2000),
  -- The schedule. A new card is due at once.
  due_at timestamptz not null default now(),
  interval_days integer not null default 0 check (interval_days between 0 and 365),
  ease_factor numeric(3, 2) not null default 2.50 check (ease_factor between 1.30 and 3.50),
  repetitions integer not null default 0 check (repetitions >= 0),
  lapses integer not null default 0 check (lapses >= 0),
  last_reviewed_at timestamptz,
  scheduler_version text not null default 'sm2-v1'
    check (char_length(scheduler_version) between 1 and 20),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint flashcards_id_user_id_key unique (id, user_id),
  constraint flashcards_goal_fk
    foreign key (goal_id, user_id) references public.learning_goals (id, user_id) on delete cascade,
  constraint flashcards_item_fk
    foreign key (item_id, user_id) references public.roadmap_items (id, user_id) on delete cascade
);

comment on table public.flashcards is
  'A learner''s own flashcard with its spaced-repetition schedule. Written by the learner via the API.';

create index flashcards_goal_due_idx on public.flashcards (user_id, goal_id, due_at);

create trigger flashcards_set_updated_at
  before update on public.flashcards
  for each row execute function public.set_updated_at();

-- A topic named by a card must belong to one of the same goal's roadmaps. Runs as the caller
-- (SECURITY INVOKER), who can only see their own rows, which is exactly the check wanted.
create function public.flashcards_check_topic()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if new.item_id is not null and not exists (
    select 1
    from public.roadmap_items i
    join public.roadmaps r on r.id = i.roadmap_id and r.user_id = i.user_id
    where i.id = new.item_id
      and i.user_id = new.user_id
      and r.goal_id = new.goal_id
  ) then
    raise exception 'A flashcard''s topic must belong to the same goal'
      using errcode = '23514', constraint = 'flashcards_topic_of_goal';
  end if;
  return new;
end;
$$;

create trigger flashcards_topic_of_goal
  before insert or update of item_id, goal_id on public.flashcards
  for each row execute function public.flashcards_check_topic();

alter table public.flashcards enable row level security;

create policy flashcards_select_own on public.flashcards
  for select to authenticated
  using (user_id = (select auth.uid()));

create policy flashcards_insert_own on public.flashcards
  for insert to authenticated
  with check (user_id = (select auth.uid()));

create policy flashcards_update_own on public.flashcards
  for update to authenticated
  using (user_id = (select auth.uid()))
  with check (user_id = (select auth.uid()));

create policy flashcards_delete_own on public.flashcards
  for delete to authenticated
  using (user_id = (select auth.uid()));

revoke all on table public.flashcards from anon, authenticated;

grant select on table public.flashcards to authenticated;

grant insert (user_id, goal_id, item_id, origin, front, back)
  on table public.flashcards to authenticated;

grant update (item_id, front, back, due_at, interval_days, ease_factor, repetitions, lapses,
              last_reviewed_at, scheduler_version)
  on table public.flashcards to authenticated;

grant delete on table public.flashcards to authenticated;

-- --- flashcard_reviews: the append-only history ----------------------------------------------------

create table public.flashcard_reviews (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null,
  card_id uuid not null,
  rating text not null check (rating in ('again', 'hard', 'good', 'easy')),
  scheduler_version text not null check (char_length(scheduler_version) between 1 and 20),
  reviewed_at timestamptz not null default now(),
  -- The schedule before and after, so history can be replayed under a different algorithm.
  interval_before integer not null check (interval_before between 0 and 365),
  ease_before numeric(3, 2) not null check (ease_before between 1.30 and 3.50),
  interval_after integer not null check (interval_after between 0 and 365),
  ease_after numeric(3, 2) not null check (ease_after between 1.30 and 3.50),
  repetitions_after integer not null check (repetitions_after >= 0),
  lapses_after integer not null check (lapses_after >= 0),
  due_after timestamptz not null,
  -- The same key on the same card is the same review.
  idempotency_key text
    check (idempotency_key is null or char_length(idempotency_key) between 8 and 128),
  constraint flashcard_reviews_card_fk
    foreign key (card_id, user_id) references public.flashcards (id, user_id) on delete cascade
);

create unique index flashcard_reviews_idempotency_idx
  on public.flashcard_reviews (card_id, idempotency_key)
  where idempotency_key is not null;

create index flashcard_reviews_card_idx on public.flashcard_reviews (card_id, reviewed_at desc);
create index flashcard_reviews_user_day_idx on public.flashcard_reviews (user_id, reviewed_at desc);

alter table public.flashcard_reviews enable row level security;

create policy flashcard_reviews_select_own on public.flashcard_reviews
  for select to authenticated
  using (user_id = (select auth.uid()));

create policy flashcard_reviews_insert_own on public.flashcard_reviews
  for insert to authenticated
  with check (user_id = (select auth.uid()));

revoke all on table public.flashcard_reviews from anon, authenticated;

grant select on table public.flashcard_reviews to authenticated;

grant insert (user_id, card_id, rating, scheduler_version, interval_before, ease_before,
              interval_after, ease_after, repetitions_after, lapses_after, due_after,
              idempotency_key)
  on table public.flashcard_reviews to authenticated;
