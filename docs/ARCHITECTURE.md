# StudyPilot — Architecture

| | |
|---|---|
| **Status** | Draft v0.1 — design only; nothing below is implemented yet |
| **Date** | 2026-10-09 |
| **Related** | [PRD.md](PRD.md) · [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) |

Markers used in this document:

- **[verify]** — depends on an external product's current behaviour (Supabase, Next.js, AI SDKs). Confirm against official documentation at the milestone that first needs it. Do not treat it as settled.
- **[spike]** — a short, time-boxed experiment scheduled inside a milestone to de-risk a design decision.
- **(M#)** — the milestone in which the item is built. See [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md).

---

## 1. Principles

1. **Modular monolith.** One deployable Python package with two entrypoints (API and worker). No microservices.
2. **The API owns the business.** FastAPI owns authorization, grading, AI orchestration and privileged operations. Next.js owns presentation only and must not re-implement business rules or expose a second business API.
3. **Defence in depth for data.** Ownership is checked in the service layer *and* enforced by PostgreSQL row-level security (RLS). Neither is trusted to be sufficient alone.
4. **AI is a workflow, not an agent.** Explicit stages, typed contracts, validation by code, bounded retries, cost caps.
5. **One source of truth per concern.** Schema → Supabase SQL migrations. API contract → FastAPI's OpenAPI document. Jobs → one PostgreSQL-backed queue.
6. **Mobile-ready.** Everything the web client does goes through the same HTTP contract an Expo client will use.
7. **Incremental, vertical slices.** Every milestone ships a complete, tested, user-visible workflow (see the Definition of Done in the plan).

## 2. System overview

```
 Browser — Next.js (Vercel)                 Mobile — Expo (P2)
    │  ╲__ Supabase Auth (sign-in/up, token refresh) — supabase-js, direct
    │
    │  HTTPS + Authorization: Bearer <Supabase access token>
    ▼
 ┌────────────────────────── FastAPI  (services/api) ──────────────────────────┐
 │ middleware: request-id · CORS allow-list · rate limit · problem+json errors │
 │ dependency: verify JWT  →  Principal(user_id)                               │
 │ routers (thin) → services (rules) → repositories (SQL) → user-scoped session│
 └──────┬───────────────────────────┬─────────────────────────┬────────────────┘
        │                           │                         │ enqueue = INSERT row
        ▼                           ▼                         ▼
 Supabase PostgreSQL         Supabase Storage          generation_jobs table
 (RLS · pgvector · FTS)      (private buckets)                  ▲
        ▲                           ▲                           │ claim: FOR UPDATE SKIP LOCKED
        └───────────────────────────┴──────────── Worker (same image: python -m app.workers)
                                                    │
                                   ┌────────────────┼──────────────────┐
                                   ▼                ▼                  ▼
                           LLMProvider       Text extractors      YouTube Data API
                        (Gemini / OpenAI)   (pypdf · vision OCR)   (resource curator)
```

Key properties:

- **Browser/mobile ↔ Supabase** only for Auth (and, if chosen in M6, direct-to-Storage signed uploads). All application data goes through FastAPI. The Supabase Data API (PostgREST) is **not** exposed for application tables (ADR-004).
- **Browser/mobile ↔ FastAPI** directly with a Bearer token. No Next.js proxy layer (ADR-005).
- **Long-running work never runs in a request.** The API inserts a job row and returns its ID; the worker does the rest.

## 3. Repository structure

Proposed layout. Directories are created by the milestone that first needs them, not up front.

```
StudyPilot/
├─ apps/
│  ├─ web/                      # Next.js App Router · React · strict TypeScript · Tailwind · shadcn/ui · e2e/ (Playwright)   (M1)
│  └─ mobile/                   # Expo / React Native                                                     (P2)
├─ services/
│  └─ api/                      # FastAPI + worker — one Python package, two entrypoints                  (M1)
│     ├─ pyproject.toml · uv.lock · .python-version · Dockerfile
│     ├─ app/
│     │  ├─ main.py             # ASGI app factory
│     │  ├─ api/v1/             # routers — thin: parse, authorize, call a service, shape the response
│     │  ├─ core/               # config, security (JWT), logging, errors, db (RLS-scoped transactions), request context
│     │  ├─ schemas/            # Pydantic request/response DTOs
│     │  ├─ repositories/       # data access only; no business rules
│     │  ├─ services/           # goals · roadmaps · lessons · assessments · progress · documents · resources · exports
│     │  ├─ ai/
│     │  │  ├─ providers/       # LLMProvider interface + gemini / openai / fake adapters
│     │  │  ├─ orchestration/   # job handlers, stage runner, checkpoints
│     │  │  ├─ prompts/         # versioned prompt templates
│     │  │  ├─ retrieval/       # hybrid search
│     │  │  ├─ ingestion/       # extract · chunk · embed
│     │  │  └─ validators/      # deterministic plan / lesson / quiz validators
│     │  └─ workers/            # queue claim loop, lease/heartbeat, retry policy, handlers registry
│     └─ tests/                 # auth/ · db/ · api/ · supabase_stack/ · support/ · pg_server/ (+ ai_eval/ later)
├─ packages/
│  └─ contracts/                # generated TypeScript types + typed fetch client from OpenAPI   (M1)
├─ supabase/
│  ├─ config.toml
│  ├─ migrations/               # SINGLE SOURCE OF TRUTH for the database schema
│  ├─ templates/                # Auth email templates (confirmation.html)
│  └─ seed.sql                  # development fixtures only (no AI-generated content)
├─ docs/                        # PRD · ARCHITECTURE · IMPLEMENTATION_PLAN · runbooks
├─ .github/workflows/           # CI
├─ .devcontainer/               # optional Linux dev environment (see §15)
├─ docker-compose.yml           # api + worker containers (the database stack comes from `supabase start`)
├─ package.json                 # npm workspaces root + cross-platform scripts
├─ CLAUDE.md · README.md · .gitignore · .gitattributes
```

Notes:

- `packages/design-tokens` from the source brief is **deferred** until the Expo app exists. Until then, design tokens live as CSS variables in `apps/web` (YAGNI).
- Worker code lives inside `services/api/app/workers` so it shares models, services and providers with the API without a shared-library package. The same Docker image runs either `uvicorn app.main:app` or `python -m app.workers`.
- Layering rule, enforced by review and an import-linter check added in M3: `api → services → repositories → schemas`; `ai/*` is called by `services` and `workers`, never by `api` routers directly; nothing imports from `api`.

## 4. Components

| Component | Responsibility | Does **not** do |
|---|---|---|
| **apps/web** | Rendering, forms, client-side validation for UX, session handling with Supabase Auth, calling the API through the generated client | Business rules, grading, direct table access, secrets |
| **services/api** | JWT verification, authorization, validation, goals/roadmaps/lessons/quizzes/progress logic, job creation, signed URLs, rate and budget checks | Long-running work, direct model calls inside request handlers |
| **worker** | Claims jobs, runs AI workflows and document processing, writes results transactionally, records usage | Serving HTTP |
| **Supabase Postgres** | Relational data, RLS, pgvector, full-text search, job queue | Business logic beyond constraints, triggers for housekeeping and RLS helpers |
| **Supabase Storage** | Private documents and generated exports | Public hosting of any user file |
| **LLM provider** | Structured generation and embeddings behind `LLMProvider` | Anything that mutates state or calls tools autonomously |

## 5. Authentication and authorization

### 5.1 Authentication

- Supabase Auth issues sessions. The web app uses `@supabase/ssr` with cookie-based sessions that are read and refreshed **only on the server** (Server Components, Server Actions and the `proxy.ts` interceptor; **verified:** Next.js 16 renamed `middleware.ts` to `proxy.ts`). Session cookies are written `HttpOnly`, `SameSite=Lax` and, in deployments, `Secure`; the app never creates Supabase's browser client, so no token is readable by page scripts (ADR-023). Decisions use `getClaims()`, which verifies the token signature; `getSession()` is used only to fetch the token that is then sent to the API, never to decide who someone is.
- The API verifies the Bearer token on every protected request (`app/core/security.py`): signature, `exp`, `aud` (`authenticated`), `iss`, a canonical-UUID `sub`, `role = authenticated`, and not anonymous. Two verification modes are selected by config, each with its **own algorithm allow-list**, so `none` and key-confusion attacks are refused:
  - **JWKS** (`ES256`/`RS256` only) — preferred; keys fetched from the project's JWKS endpoint (`/auth/v1/.well-known/jwks.json`), cached, with a refetch cooldown for unknown `kid`s and stale-if-error behaviour.
  - **HS256 shared secret** (`HS256` only) — for legacy projects and, where the local stack issues them, local tokens.
  **Spike S2 (outcome):** Supabase's documentation (checked 2026-10-10) confirms the endpoint, a ~10-minute edge cache, and that a shared secret is "not recommended for production". Both modes are tested with real signatures. Which algorithm the local CLI stack issues is detected, not assumed: the CI job reads the header of a real token and picks the mode (`.github/scripts/supabase_stack_env.py`).
- The verified identity is a `Principal(user_id, email, claims)` object. Handlers never read `user_id` from request bodies or query strings; a body that names an owner is rejected (`extra = forbid`).

### 5.2 Authorization — two independent layers

1. **Service layer.** Every service method takes a `Principal` and loads resources through ownership-scoped repository methods. A non-owned or non-existent resource returns **404** (not 403) so identifiers cannot be enumerated.
2. **Database RLS (ADR-006).** Application tables have RLS enabled with owner policies. For user-facing requests the API opens a transaction that drops to the `authenticated` role and sets the JWT claims, so `auth.uid()` resolves inside policies:

   ```python
   async with database.user_transaction(principal) as conn:   # BEGIN;
       ...   # set_config('role', 'authenticated', true); set_config('request.jwt.claims', <claims>, true)
             # repositories take a `UserConnection`, a NewType only this context manager produces
   ```

   Consequence: a missing `WHERE user_id = …` in a repository cannot leak another user's rows (repositories filter on `user_id` too; the database is the second lock, not the only one). A privileged `system_session()` for the worker and grading-key reads does not exist yet because no feature needs it; it arrives with the worker (M3), confined to `services/*/privileged.py` and the worker, with a test that no router imports it. **Spike S1 (outcome):** verified on real PostgreSQL 16 through psycopg 3 and a connection pool, including a test that a pooled connection does not keep the previous caller's role or claims. Both settings are transaction-local and prepared statements are disabled, so the same code works behind Supabase's session pooler (the one we use) and transaction pooler. Confirmation under Supabase's own roles is the `supabase-stack` CI job.

### 5.3 What each credential can do

| Credential | Where it lives | Power | Never in |
|---|---|---|---|
| Anon / publishable key | Browser, mobile | Auth endpoints; no table access (grants revoked) | — |
| User access token (JWT) | Browser memory/cookie → API `Authorization` header | Acts as one user | Logs |
| Service-role / secret key | API and worker env only | Storage admin, signed URLs, auth admin | Any client bundle, Git, logs |
| Database URL | API and worker env only | Full DB access via the privileged session | Any client bundle, Git, logs |
| LLM / YouTube keys | API and worker env only | Spend money | Any client bundle, Git, logs |

## 6. Data model and migration strategy

### 6.1 Strategy

- **Source of truth: `supabase/migrations/*.sql`** (timestamped, forward-only), applied with the Supabase CLI. **Alembic is not used** (ADR-002): RLS policies, grants, `auth.users` triggers, storage policies and extensions are Supabase-native and are written directly in SQL.
- **psycopg 3 with explicit SQL** is the data-access layer (ADR-021, which supersedes the SQLAlchemy plan). Repositories are small modules of parameterised SQL returning Pydantic row models, so there are no ORM models to drift from the migrations; a schema change that breaks a query fails the database and API tests.
- **Grants are explicit.** Supabase gives `anon`, `authenticated` and `service_role` default privileges on new `public` tables; every migration revokes them and grants back only what the API needs (column-level `insert`/`update` grants where a field must not be client-controlled). A guard test fails the build if a `public` table lacks RLS or grants anything to `anon` (`tests/db/test_db_guards.py`).
- **One migration per slice**, not one 17-table migration up front. Each migration contains, together: the tables, constraints, indexes, `enable row level security`, owner policies, explicit `grant`/`revoke`, and its database tests in `services/api/tests/db/` (ADR-022). No table ships without RLS and a test. This replaces the source brief's "migrate everything first" suggestion because policies are only trustworthy if they are tested with the table that introduced them.
- **Forward-only.** Fixes are new migrations. Destructive changes use expand → migrate → contract.
- **Environments.** Local: `supabase start` + `supabase db reset` (needs Docker; see §15). Hosted dev/staging/prod: `supabase link` + `supabase db push`, run by CI on merge (staging automatic, production behind manual approval).
- **Seed data** (`seed.sql` / a script that calls the Auth admin API) creates development users and user-authored goals only. **No fake AI-generated lessons, roadmaps or quizzes** are ever seeded to make the product look complete.

### 6.2 Tables by milestone

All user-data tables carry `user_id uuid not null` (denormalised on children for cheap, index-friendly RLS) and have RLS enabled.

| Table | M | Notes and changes relative to the source brief |
|---|---|---|
| `profiles` | M1, M2 | `id` = `auth.users.id`. Created by an `after insert on auth.users` trigger (security definer) plus a backfill. M2 adds the learner's persistent defaults — `default_daily_minutes`, `preferred_languages`, `learning_preferences` — and `onboarding_completed_at` (ADR-025). Clients may update only those columns and the display fields. |
| `learning_goals` | M1, M2 | `goal_type` constrained to the intent-parser vocabulary (`exam`, `academic_subject`, `professional_skill`, `certification`, `interview`, `general`) — the source schema's default `'skill'` did not match its own `LearningGoalSpec`. `current_level` includes `unknown` so a guess is never stored as fact. Length and range checks on title, `daily_minutes` and `preferred_languages`. M2 adds `learning_preferences`, `completed_at` and `archived_at`, a lifecycle trigger and an owner-only, archived-only delete policy (ADR-025). |
| `generation_jobs` | M3 ✅ | The queue (ADR-003): `job_type` (`roadmap`, `lesson`, `quiz` or `grade`; a lesson or quiz job also names its roadmap item in `item_id`, a grading job its `attempt_id`; one active job per topic and kind, one per attempt), `status`, `stage` and `progress` for the UI, `attempts` / `max_attempts`, `run_at`, `locked_by` / `locked_until` (the lease), `cancel_requested`, `request` (what the learner asked for), `checkpoint` (the validated plan, so a retry does not pay twice) and a learner-safe `error_code` / `error_message`. Composite FK `(goal_id, user_id)`. A partial unique index allows **one queued or running roadmap job per goal**, another **one queued or running lesson job per topic**; another makes `(user_id, idempotency_key)` unique. Check constraints tie the lock, `finished_at` and the error to the status. A `document` job names its document in `document_id` (**one active job per document**, M6). Learners may read their rows, insert a job (six columns) and raise `cancel_requested`; a trigger turns a cancel of a queued job into `cancelled`; a second trigger refuses a lesson job whose item is not a topic (or optional extra) of the goal's *current* roadmap (M4, ADR-032). Everything else is the worker's. |
| `ai_usage_events` | M3 ✅ | One row per model call, success or failure: job, purpose (`roadmap.plan` / `roadmap.repair` / `lesson.write` / `lesson.repair` / `quiz.write` / `quiz.repair` / `grade.short_answer` / `grade.repair`), provider, model id, prompt version, tokens in/out, latency, finish reason, error code. Written by the worker; read-only to the owner. Cost columns arrive with budgets. |
| `roadmaps` | M3 ✅ | A **version** of a goal's plan (ADR-029): `unique (goal_id, version)`, `unique (job_id)` (one roadmap per job, so a retry cannot store a second), a partial unique index allowing one `current` version per goal. Title, overview, target outcome, language, `syllabus_basis` (`learner_stated` / `uploaded_document` / `general_knowledge`, never "official"), assumptions, unknowns, objectives and evidence (`jsonb`), totals computed from the stored items, the constraints it was planned for (`daily_minutes`, `target_date`), the revision note, `based_on_roadmap_id`, prompt version, provider, model and `is_synthetic`. Content is immutable: clients hold `select` and `update (status)` only, and cannot switch versions of an archived goal (trigger). |
| `roadmap_modules`, `roadmap_items` | M3 ✅ | Modules (ordered) and their items. An item is a `topic` (needs a module, a practice task and a day), a `revision` session (a day, no module) or `enrichment` (optional, **no day**: not scheduled). `item_key` is a stable slug unique within the roadmap; `position` orders items for display. Composite FKs keep an item's module and roadmap together and under one `user_id`. (Changed from the plan above: no `parent_item_id` or `topic_key`; modules are their own table.) `last_section_index` / `last_studied_at` arrive with lessons (M4). |
| `roadmap_item_prerequisites` | M3 ✅ | `(item_id, prerequisite_id)` within one roadmap, never self-referencing. For a revision session the prerequisites are the topics it revisits. Acyclicity is guaranteed by code: a prerequisite must come earlier in plan order (validated before storing). |
| `lessons` | M4 ✅ | A **version** of one topic's lesson (ADR-032; replaces the source brief's `learning_materials`): `unique (item_id, version)`, `unique (job_id)` (one lesson per job), one `current` per topic (partial unique index). `content` is the typed `Lesson` document as `jsonb` (validated by Pydantic before it is stored and again whenever it is read), with `content_version`, the section ids (`s1`…, the keys progress is recorded against), `adjust` / `revision_feedback` / `based_on_lesson_id` for a regeneration, prompt version, provider, model and `is_synthetic`. Composite FKs tie it to the learner, its roadmap, its item and its job. **Clients hold `select` only**: the worker is the only writer, so lesson content can never be written from a browser. |
| `lesson_progress` | M4 ✅ | One row per lesson version the learner has started: `status` (`in_progress` / `completed`), `completed_section_ids`, `current_section_id` (where to resume) and timestamps. A trigger guarantees that it only names the lesson's own sections, once each, that `completed` means every section is done, that `last_studied_at` is set by the database, and that it is read-only once the goal is archived. Clients may insert and update the learner-owned columns only (ADR-035). |
| `quizzes` | M5 ✅ | One quiz written from one lesson version (ADR-038): `purpose` (`check` or `practice`), `focus_objective_ids` (what a practice quiz aims at, chosen by the server), `lesson_id`, `unique (job_id)` (one quiz per job), `is_synthetic`, the prompt version, provider and model. Written only by the worker; read-only to the owner. |
| `questions` | M5 ✅ | Prompt, `kind` (`multiple_choice`, `true_false`, `short_answer`), `options` (`[{id, text}]`, null for a short answer; a check refuses a missing or wrongly sized list), `objective_id`, `difficulty` and `max_points` (1/2/3, which is also its weight in mastery), `position`. **No answer key, no explanation.** Read-only to the owner. |
| `question_answer_keys` | M5 ✅ | **New.** `question_id` PK; either `correct_option_id` or a `rubric` plus `model_answer` (a check allows exactly one kind), `explanation`, per-option `option_notes`. Row security is on with **no policy and no grant for any client role**; only `app/grading` reads it (ADR-007, ADR-036) and the worker writes it. The source schema put the key beside the prompt, and RLS is row-level, so a policy that lets a learner read their own questions would also have let them read the answers. |
| `quiz_attempts`, `quiz_answers` | M5 ✅ | `user_id` added to `quiz_answers` (the source had none). **`unique (quiz_id)`: a quiz is attempted once** (ADR-038); a per-user partial unique index on `idempotency_key` makes a repeated form post return the same attempt. An answer holds what the learner sent, `grading_method` (`deterministic`, `ai_estimate`, `self_review`, `pending`), `points_awarded` (null exactly while `pending`, never above `max_points`) and a **copy of the feedback** (right option, explanation, rubric, model answer, matched points) taken from the key at submission, so reading a result never touches the key table. Written only by the grader and the worker; read-only to the owner. |
| `topic_mastery` | M5 ✅ | One row per topic: score, per-objective scores, answer and attempt counts, `algorithm_version`. A **cache** of `compute_mastery` over the stored answers (ADR-036): it can be deleted and rebuilt at any time. The band and the "early estimate" flag are derived from the score with the current thresholds each time they are read, so changing a threshold needs no migration. |
| `source_documents` | M6 ✅ | One document of a goal's study material (ADR-039…045): `kind` (`pdf`, `text`, `image`, `pasted`: decided from the bytes), `size_bytes`, `sha256` (**one copy of a file per goal**), `storage_path` (`{user_id}/{document_id}/{safe name}`, a check ties it to the owner), `status` (`queued` → `processing` → `ready`, or `review`, or `failed`), a learner-safe `error_code` / `error_message`, `warnings` (jsonb), counts and `embedding_model`. Pasted text is stored as a small text file too, so there is one pipeline. Composite FK `(goal_id, user_id)`. Clients may add (as `queued`), rename and send a document to be processed again; a trigger refuses every other status change from a client and any write once the goal is archived. |
| `document_pages` | M6 ✅ | **New.** The text taken from a document, one row per page (or per part of a text): `text`, `source` (`text_layer`, `ocr`, `text`), `legibility` for pages read from a picture, `needs_review`, `edited`. Written only by the worker; a learner may correct `text` **only while the document waits for their review** (trigger). |
| `document_chunks` | M6 ✅ | The searchable passages: `page_start` / `page_end`, `section_title`, `content`, `embedding vector(1536)`, `embedding_model`, and a generated `tsvector` (`simple` configuration, GIN index). A composite FK `(document_id, goal_id, user_id)` makes a passage belong to one document, goal and learner at once. Read-only to its owner; written only by the worker, in the same transaction that marks the document `ready`. |
| `learning_resources` | M7 | As in the source brief (the flashcard tables are in the rows above, ADR-050; a `resources` migration for it was recovered from the hosted project, and its code is not in this repository). |
| `content_reports` | M7 | **New.** Learner reports of incorrect lessons, questions or resources (FR-18). |
| `exports` | M8 | As in the source brief. |
| `flashcards` | M7 ✅ | A learner's own card (ADR-050): `goal_id`, optional `item_id` (a trigger refuses a topic of another goal), `front` / `back`, `origin` (`manual`), and its schedule (`due_at`, `interval_days` 0 to 365, `ease_factor` 1.30 to 3.50, `repetitions`, `lapses`, `last_reviewed_at`, `scheduler_version`). The learner may write the sides and, through the API, the schedule; nothing graded or shared depends on it. Not insertable with a schedule, and `goal_id` / `user_id` are fixed at creation. |
| `flashcard_reviews` | M7 ✅ | Append-only history (ADR-050): `rating`, `scheduler_version`, the interval and ease **before and after**, `due_after`, and an `idempotency_key` unique per card. Learners can read and add, never change or delete (a review goes only with its card or goal). |

### 6.3 Patterns every table follows

Illustrative patterns — **not yet applied or tested**; the real DDL arrives with the milestone's tests.

```sql
-- Ownership enforced by the database across parent → child, not just by convention:
alter table public.roadmaps add constraint roadmaps_id_user_uniq unique (id, user_id);
create table public.roadmap_items (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null,
  roadmap_id uuid not null,
  -- … columns …
  foreign key (roadmap_id, user_id)
    references public.roadmaps (id, user_id) on delete cascade
);

-- RLS: deny by default, explicit owner policies, auth.uid() wrapped for plan caching:
alter table public.roadmap_items enable row level security;
create policy roadmap_items_owner_select on public.roadmap_items
  for select to authenticated using (user_id = (select auth.uid()));
-- … separate insert / update / delete policies …

-- Least privilege, stated explicitly rather than relying on platform defaults:
revoke all on public.roadmap_items from anon;
grant select, insert, update, delete on public.roadmap_items to authenticated;
```

Further rules: UUID primary keys; `timestamptz` everywhere; `updated_at` maintained by a shared trigger; status columns have `check` constraints; deliberate `on delete` behaviour per FK; indexes on every FK and on common list orderings; `unique` constraints wherever duplicates would be a bug; cursor pagination on list endpoints.

### 6.4 Vectors and search (M6, implemented — ADR-041, ADR-045)

- `document_chunks.embedding` is `extensions.vector(1536)` (pgvector, in the `extensions` schema). The column type is the dimension check: nothing but 1536 numbers can be stored. Each chunk records `embedding_model`.
- **There is deliberately no ANN (HNSW/IVFFlat) index yet.** Search is always limited to ONE learner's ONE goal, so the rows scanned are a few hundred or thousand and an exact scan is fast and exact; a shared approximate index would also return too few rows once other learners' vectors fill its candidate list (the filter would be applied after the index). Add an index, with filtered-search tests, when a goal can hold enough chunks to measure a problem.
- Retrieval (`app/retrieval/search.py`) is hybrid and filtered **inside the SQL**: the semantic ranking (cosine distance, `OPERATOR(extensions.<=>)`, schema-qualified so it never depends on `search_path`) and a full-text ranking (`to_tsquery('simple', …)` over the question's words joined with OR, `ts_rank_cd`) are fused with reciprocal rank fusion (k = 60, 40 candidates each). The `simple` configuration does no stemming or stop-word removal, so it works the same for English, Hindi and Odia text.
- A passage is returned only if it clears a **similarity bar** (`RETRIEVAL_MIN_SIMILARITY`, 0.58 by default, calibrated on a small live sample with gemini-embedding-001: matching passages scored 0.69-0.78 against their questions and unrelated ones 0.42-0.52), or shares words with the question and reaches 85 % of the bar. **No result is a valid answer**: callers say that the material does not cover the question instead of guessing. The built-in test embedder has a lower bar (0.1) because its vectors are word-overlap hashes, not meaning.
- Every statement filters on `user_id` and `goal_id` and only searches `ready` documents. The API runs it in the learner's own row-security-scoped transaction (so the database also refuses anything that is not theirs); the worker, which has no row security, relies on the explicit filter, and tests prove both.
- No separate vector database until measured latency, volume or isolation needs justify one.

### 6.5 Deletion and retention (implemented for documents, M6 — ADR-040)

- **A document**: `DELETE /v1/documents/{id}` deletes the file from private storage first (as the learner), then the row; pages, passages and the document's jobs go with the row (`on delete cascade`). A document that is being processed cannot be deleted (409). Nothing about it is kept: not the text, not the vectors, not the file.
- **A goal**: only an archived goal can be deleted; its files are deleted from storage first, then its rows cascade.
- **Lessons keep their wording but not the document.** A lesson stores the ids of the passages it cites, never a copy of them; once the document is gone its citations read "a document you have since deleted", with no text.
- **An account**: deleting a `profiles`/`auth.users` row cascades to every database row, but **a row delete never removes a Storage object**. There is no in-app account deletion yet; until it exists (M9), deleting an account directly in Supabase leaves the files under `{user_id}/` in the `documents` bucket until that folder is removed from Storage (documented in SUPABASE_SETUP.md). This is a known gap, not a hidden one.
- **Job payloads**: the signed link a document job carries is removed from the job's `request` as soon as the job ends (finished, failed or cancelled); it also expires after `DOCUMENT_SIGNED_URL_SECONDS`.
- Retention windows for other job payloads and logs are configuration, defaulted conservatively, and documented in M9.

## 7. Job queue

**Status:** implemented for roadmap generation (M3), lesson writing (M4), quiz writing and short-answer marking (M5) and document processing (M6); one worker runs all five kinds of job. A `document` job runs one of two tasks (`extract`: read the file, then index it unless the learner must check the text first; `index`: embed the stored pages), checkpoints by replacing pages and passages atomically, and **always leaves its document in a final state**: the runner marks the document failed when the job fails for good or is cancelled, and the worker's reaper settles documents whose job ended without saying so. The worker is `python -m app.worker`; the claim, lease, heartbeat, reaper, retry-with-backoff, checkpoint and cancel behaviour below is covered by tests against a real PostgreSQL (`tests/jobs`). Not yet built: `LISTEN/NOTIFY` wake-ups, per-provider rate limiting shared across jobs, and the daily *cost* budget (a per-learner daily *count* limit exists).

**Decision (ADR-003):** a PostgreSQL-backed queue on `generation_jobs`, polled by a worker. No Redis, Celery or second broker — one durable store, transactional enqueue, one thing to operate. Revisit only if measured throughput requires it; Procrastinate is the first alternative to evaluate.

```
            ┌──────────── retryable error & attempts < max ──────────────┐
            ▼                                                            │
 queued ──claim──► running ──success──► completed                        │
   ▲                  │  ╲                                               │
   │                  │   ╲── non-retryable / attempts exhausted ► failed│
   │                  │                                                  │
   │                  └── lease expires (worker died) ───────────────────┘
   └── manual retry by owner (only if failed with a retryable code and budget remains)
 any state ──cancel──► cancelled
```

- **Enqueue.** The API writes the job row in the same transaction as any related domain write. `POST` endpoints that create jobs accept an `Idempotency-Key` header; the same key and payload returns the existing job, the same key with a different payload returns **409**.
- **Claim.** `UPDATE … WHERE id = (SELECT id … WHERE status='queued' AND run_at <= now() ORDER BY priority, created_at FOR UPDATE SKIP LOCKED LIMIT 1) RETURNING *`.
- **Lease and heartbeat.** A claimed job holds `locked_until`; the worker extends it while working. A reaper requeues (or fails, if attempts are exhausted) running jobs whose lease expired.
- **Retries.** Bounded by `max_attempts`, exponential backoff with jitter into `run_at`. Only errors classified retryable (timeouts, 429/5xx, transient validation failures) are retried; budget-exhausted, invalid-input and policy errors fail immediately. No silent infinite retries of expensive work.
- **Checkpointing (ADR-017).** Each completed stage writes its output to `progress`/`output_json`. A retry resumes at the first incomplete stage, so a retry never re-pays for finished stages.
- **Exactly-once effects.** Final writes are transactional and keyed (for example `roadmaps.job_id` is unique), so a retry or double-claim cannot create a second roadmap.
- **Cancellation.** `cancel_requested` is checked between stages.
- **Concurrency.** `WORKER_CONCURRENCY` bounds parallel jobs in one process; per-provider rate limiting is shared across them.
- **Wake-up.** Polling with jitter at first. `LISTEN/NOTIFY` is an optimisation that needs a session-mode or direct connection and is deferred.

## 8. AI layer

### 8.1 Provider abstraction (ADR-009)

```python
class LLMProvider(Protocol):
    async def generate_structured(self, request: StructuredRequest, schema: type[T]) -> StructuredResult[T]: ...
    async def embed(self, texts: Sequence[str], task: EmbeddingTask) -> EmbeddingResult: ...
    async def read_image_text(self, image: bytes, mime_type: str) -> OcrResult: ...   # vision OCR, M6
```

- Every result carries `model_id`, token usage, latency and finish reason, which are written to `ai_usage_events`.
- Adapters: `GeminiProvider` (first, assumption A4), `OpenAIProvider` (second), `FakeProvider` (tests and explicit local development only).
- **`FakeProvider` is refused when `APP_ENV` is `staging` or `production`**, and any job that used it is marked in its output so the UI can label the content as synthetic. It exists to make tests deterministic, not to fabricate a finished product.
- Structured output uses the provider's native schema-constrained generation where available, and **always** re-validates with Pydantic. Free-form JSON scraping is not used. **[verify]** current Gemini/OpenAI SDK APIs and model names before writing adapters (M3); SDK major versions have moved since the source brief was written.
- Every call has a timeout, a retry limit, a maximum output size and a per-job token ceiling.
- **Implemented (ADR-027):** `LLMProvider` and typed errors in `app/ai/provider.py`; `GeminiProvider` over Gemini's REST API (`app/ai/gemini.py`); `FakeProvider` (`app/ai/fake.py`, labelled `synthetic`); the roadmap planner, its versioned prompt (`roadmap-planner/v2`), schema and validators in `app/ai/roadmap/`. OpenAI is not built. **Embeddings and OCR are implemented (M6, ADR-041…045):** `embed` (Gemini `batchEmbedContents` with `outputDimensionality` 1536, vectors scaled to length 1 in code, at most 100 texts per request, separate `RETRIEVAL_DOCUMENT` / `RETRIEVAL_QUERY` task types) and `read_image_text` (a vision call on one image or single-page PDF, answering a small structured reply: the transcription and how legible it was). Both are recorded in the usage ledger like any other call (counts and codes only). Gemini calls were exercised against a mock transport; a live call needs `GEMINI_API_KEY` (see the status notes in IMPLEMENTATION_PLAN §4.6).

### 8.2 Workflow stages

Deterministic orchestration, not autonomous agents. A job type selects which stages run; text-only roadmap generation runs without retrieval or YouTube.

| # | Stage | Uses LLM | Input → output | Validation (by code) |
|---|---|---|---|---|
| 1 | Intent parser | Yes (small) | Goal form + free text → `LearningGoalSpec` | Schema; must not invent dates, levels or syllabus; unknown stays `null` |
| 2 | Document retrieval ✅ (M6) | No (one embedding call) | Topic → evidence set | Ownership and goal filter in SQL; similarity bar; empty evidence is a valid result (§6.4). The lesson job runs it; the learner can also search directly |
| 3 | Curriculum planner | Yes | Spec + evidence → `Roadmap` | **Programmatic**: total minutes vs budget, prerequisite DAG is acyclic and ordered, every objective covered, unique sequence. One bounded repair attempt with the violations fed back; otherwise fail `PLAN_INVALID` |
| 4 | Lesson generator ✅ (M4) | Yes | One roadmap item + evidence → `Lesson` | Schema; every citation label ∈ the labels supplied (the model sees `S1`/`P2`, code swaps in the real ids, ADR-044); no page numbers when it rests on the learner's material; no empty blocks or thin sections; no links or DOIs; language; length budget; a simple explanation that is not just the summary. One bounded repair (ADR-033) |
| 5 | Assessment generator ✅ (M5) | Yes | Item + lesson → questions | `build_quiz` + `validate_quiz`: exactly one correct option; unique, non-empty options; no "all of the above" or near-identical options; objective ID exists on the item and every focus objective is covered; the right answer is not in the question and the explanation does not defend a wrong option; duplicate and repeat-of-earlier-quiz detection; kind mix, difficulty mix and language; no links; the options are shuffled by code (seeded) so the answer is not always first; keys are stored separately. One bounded repair, then `QUIZ_INVALID` |
| 5b | Short-answer marker ✅ (M5) | Yes | Answer + fixed rubric → which rubric points are met | The reply must name each answer once and only rubric points that exist; the **score is added up by code** from the points marked met; the learner's answer is fenced as data; the result is labelled an **AI estimate** and the learner can replace it (ADR-037). One bounded repair, then `GRADING_INVALID` (the answer stays pending) |
| 2b | Page reader ✅ (M6) | Yes (vision) | One scanned page or picture → its text | Treated as data, never instructions; anything but `clear` legibility waits for the learner's review (ADR-042); capped pages per document |
| 6 | Resource curator | No (tool) | Topic + languages → ranked videos | Results come only from the YouTube API; cached; `last_verified_at` set (M7) |
| 7 | Quality gate | No | All stage outputs → pass/fail with reasons | Aggregates validators; failure never persists partial content as published |
| 8 | Persist & complete | No | Validated output → rows | Single transaction; keyed for exactly-once effect |

Lesson and quiz generation operate on **one roadmap item at a time**, never an entire curriculum in one request.

### 8.3 Prompts

- Stored in `app/ai/prompts/<stage>/vN` as versioned templates. The prompt version, model id and generation settings are recorded on every output (`learning_materials`, `ai_usage_events`).
- Learner text and extracted document text are inserted only inside clearly delimited **data** blocks, and the system prompt states that such content is reference data and never instructions (prompt-injection posture, §13).
- Prompt changes are reviewed like code and covered by the evaluation fixtures (§14).

### 8.4 Deterministic learning logic (ADR-010)

- **Grading (implemented, M5).** Objective questions are graded by code by comparing option ids (`app/grading`). Short answers are marked against a rubric fixed with the question, marked as an AI estimate, and the learner can overrule the estimate (ADR-037).
- **Mastery (implemented, M5; `app/learning/mastery.py`).** Per topic: `score = 100 · Σ(w · earned/possible) / Σ(w)` over the learner's graded answers, where `w = difficulty weight (1/2/3) × decay^rank` and rank 0 is the newest attempt (decay 0.7 by default). The same formula over the answers that test one objective gives that objective's score, which is how a weak part of a topic is found. Bands: below `MASTERY_NEEDS_PRACTICE_BELOW` (70) needs practice, from `MASTERY_MASTERED_FROM` (90) mastered, in between getting there; fewer than `MASTERY_MIN_ANSWERS` (4) answers is flagged an early estimate. These are tunable product rules (configuration, not model output) and the score is stored with `algorithm_version = weighted-recency/v1` over the stored attempts, so the method can change without losing history.
- **Spaced repetition.** SM-2-style scheduling from the `flashcards` columns (`ease_factor`, `interval_days`, `repetitions`, `lapses`), with every review stored in `flashcard_reviews` so the algorithm can be replaced (for example by FSRS) without losing history. Implemented in `app/learning/scheduling.py` as `sm2-v1` (ADR-050).
- **Next action (implemented, M5; `app/learning/recommend.py`).** A pure function of mastery and study state with no model call. In order: (1) the weakest topic that needs practice gets a short practice quiz on its lowest-scoring objectives, after going over its lesson again (never a restart of the course); (2) a topic that was studied but never assessed gets a quiz; (3) otherwise keep studying (a topic already mastered in a quiz is not "unfinished"); (4) a topic that is getting there gets one more practice quiz; (5) all mastered. The reason names the evidence. Due reviews join this function in M7.

## 9. Documents and retrieval (M6, implemented)

**Status:** the whole path is built and tested against a real PostgreSQL with pgvector (`tests/documents`, `tests/db/test_db_documents.py`, `tests/jobs/test_document_worker.py`, `tests/retrieval`, `tests/api/test_api_documents.py`, `tests/ai/test_lesson_grounding.py`, `tests/jobs/test_lesson_grounding_worker.py`) and in the browser journey. **Not exercised against the real thing:** Supabase Storage (the adapter is tested on a mock transport, see below), real Gemini embeddings/OCR on a real document (probes only), and real handwriting.

1. **Upload** (`POST /v1/goals/{id}/documents`, raw body; `/paste` for text). The API reads at most `DOCUMENT_MAX_BYTES` (10 MB; a declared `Content-Length` over it is refused before reading). **What the file is comes from its bytes** (`app/documents/sniff.py`): a PDF signature, PNG/JPEG/WebP signatures, or text that decodes as UTF-8/UTF-16 without binary content; the browser's `Content-Type` is ignored, and a name whose extension contradicts the content is refused (`FILE_TYPE_MISMATCH`, 415). Empty files, duplicates of a file already in the goal, per-goal and per-learner counts and a daily processing allowance are refused with clear codes. Storage and the AI service must be configured (503 otherwise).
2. **Store** (ADR-040). The file goes to the private `documents` bucket at `{user_id}/{document_id}/{safe name}` **using the learner's own access token**: Storage's row security lets a learner touch only objects under their own prefix, so the API never holds a service-role key. The worker has no token, so the API asks Storage for a **short-lived signed link** to that one object when it queues the job and puts it in the job's `request` (removed when the job ends). A file stored for a document that then could not be recorded is deleted again. In development and tests `DOCUMENT_STORAGE=local` keeps files in a folder (refused in staging/production).
3. **Extract** (`app/documents/extract.py`, worker). The worker re-validates size, SHA-256 and type against the row (the file came from storage, not from the checked request), then extracts with **pypdf** (pure Python, BSD; PyMuPDF is avoided for its AGPL licence, ADR-014): no rendering, no execution, bounded pages (`DOCUMENT_MAX_PAGES`), bounded text (`DOCUMENT_MAX_CHARS`), encrypted or damaged PDFs fail with a message the learner can act on. Page boundaries are kept; text files are cut into parts of about 4,000 characters at paragraph breaks. Lecture PDFs carry running headers, footers and page numbers on every page; `strip_page_furniture` removes lines that repeat at the edges of at least 40% of the pages (a document of four pages or more, a line of at most 90 characters, numbers that stay the same or follow the page index), so a repeated "Chapter 3" in the body or text in the middle of a page is never touched. Symbol-font bullets (private-use characters) become real bullets.
4. **Read pictures and scans** (ADR-042). A PDF page with no text layer, or an image, goes to the vision model (at most `DOCUMENT_MAX_OCR_PAGES` per document, one call per page, a single-page PDF being sent for PDF pages). If every page read is `clear` the job goes straight on; if any was `partly`, `poor` or unreadable the document stops in **`review`**: the learner sees the text, can correct it page by page (only in that state), and confirms; only then is it indexed. A mixed PDF whose scanned pages cannot be read still indexes its text pages, with a warning.
5. **Warnings are kept** (`source_documents.warnings`): pages without a text layer, uncertain readings, pages beyond the OCR limit, unreadable pages.
6. **Chunk** (`app/documents/chunking.py`). Passages of about `CHUNK_TARGET_CHARS` (1,200) with `CHUNK_OVERLAP_CHARS` (200) carried over, cut at headings, paragraphs and sentences, never losing text, each with the pages it spans (`page_start`/`page_end`) and the nearest heading (`section_title`). The embedded text is prefixed with the document title and heading for context; the stored passage is the plain text that is shown and cited.
7. **Embed and index** (ADR-045, ADR-046). Batches of 24, and a rate-limited batch is waited for (the service's own `retry_after`, 2 to 65 seconds, stage `waiting_rate_limit`, at most eight waits) and then retried on its own, so a limit hit midway no longer throws away the batches already embedded in that run; 1536-dimension unit vectors; count, size and model consistency are checked before anything is stored; the pages' passages are replaced in **one transaction** that also marks the document `ready` and ends the job, so a document is never half-indexed and processing again never duplicates.
8. **Retrieve** (§6.4). The learner can search a goal's documents (`POST /v1/goals/{id}/documents/search`; the question is embedded once; at most `DOCUMENT_SEARCHES_PER_USER_PER_HOUR` per process-hour, in memory). The lesson job retrieves for its topic.
9. **Cite** (ADR-044). The lesson writer is shown the passages as `source_material` with short labels (`S1`, `P2`); validation rejects any label it was not given and any page number in the prose; code then replaces labels with the real document and passage ids and sets `grounding` (`sources` / `no_match` / `none`). The study page resolves each citation as it is now (document, position, the passage) and shows "a document you have since deleted" when it is gone. When the learner has documents but nothing matched the topic, the lesson is written from general knowledge and says so.

**Uploaded content is untrusted.** Extracted text and passages only ever reach a model inside the escaped `<learner_data>` fence as data; the system prompt says passages are never instructions; the model has no tools; nothing it returns is used as an identifier, a page number or a file path without being checked against what was retrieved. Downloads are `attachment`, `nosniff`, `no-store`, never inline. Passages and extracted text are rendered as plain text, never as markup.

Malware scanning (for example ClamAV) is not in the MVP; the compensating controls are signature/size/type checks, pure-Python parsing with limits, no execution or rendering of uploaded content, and downloads as attachments only. This is a recorded risk acceptance to revisit before opening sign-ups widely.

## 10. API conventions and contracts

- **Versioned prefix** `/v1`. Resource-oriented routes; thin handlers. Implemented so far: `GET|PATCH /v1/me`, `POST /v1/me/onboarding/complete`; `POST|GET /v1/goals` (filter by `status`, cursor pagination), `GET /v1/goals/summary`, `GET|PATCH|DELETE /v1/goals/{id}`, `PUT /v1/goals/{id}/status`; `POST /v1/goals/{id}/roadmaps` (202 + a job, optional `Idempotency-Key`), `GET /v1/goals/{id}/roadmaps` (versions), `GET /v1/goals/{id}/jobs`, `GET /v1/roadmaps/{id}`, `POST /v1/roadmaps/{id}/make-current`, `GET /v1/jobs/{id}`, `POST /v1/jobs/{id}/cancel`, `POST /v1/jobs/{id}/retry`. `PATCH` changes only the fields sent; `null` clears an optional field; a status change to the current status is a no-op; `DELETE` works on archived goals only.
- **Errors:** RFC 9457 `application/problem+json` with a stable machine `code` (for example `GOAL_NOT_FOUND`, `BUDGET_EXCEEDED`, `PLAN_INVALID`) and a user-safe `detail`. Internal errors return a generic message plus the request ID; stack traces, prompts and secrets never appear in responses.
- **Pagination:** cursor-based, with `limit` bounded server-side.
- **Idempotency:** `Idempotency-Key` on job-creating POSTs.
- **Correlation:** `X-Request-ID` accepted or generated, echoed on responses, attached to every log line and propagated into job rows.
- **Health:** `/healthz` (process up) and `/readyz` (database reachable, config valid). Neither requires auth; neither reveals configuration.
- **CORS:** explicit allow-list of web origins; no wildcard with credentials.
- **Contracts (ADR-011):** FastAPI's OpenAPI document is canonical. `packages/contracts` is generated from it with `openapi-typescript` and consumed through `openapi-fetch`. CI regenerates and fails on any diff, so frontend types cannot drift from backend validation.

## 11. Frontend architecture

- **Next.js App Router**, React, TypeScript `strict`. Route groups: `(marketing)`, `(auth)`, `(app)`. The `(app)` layout requires a session.
- **Server Components** fetch data from FastAPI and **Server Actions** submit forms to it, both with the access token taken from the HttpOnly session cookie on the server (ADR-023), through the generated typed client. Client components never hold an API token. Job-status polling arrives with the first job (M3) and will go through a same-origin route that attaches the token server-side. There is no BFF layer: no business logic and no generic proxying of API paths.
- **Navigation rule (ADR-026):** a prefetchable page that depends on data shows a prompt, never a redirect. Success of a mutation is reported with a `?notice=` marker mapped through a fixed lookup table (never free text from the URL) and `revalidatePath` for the pages that show the data.
- **Forms:** native forms posting to Server Actions, validated with Zod before any network call, with the API's own field errors mapped back onto the right inputs; the API remains authoritative. React Hook Form is not used; add it only if a form needs rich client-side behaviour.
- **UI:** Tailwind CSS with design tokens as CSS variables, shadcn/ui primitives, light/dark themes, skeletons for data-dependent regions, explicit empty/error/retry states, `prefers-reduced-motion` respected, keyboard-navigable.
- **Typography:** a readable Latin face plus Noto Sans Devanagari and Noto Sans Oriya fallbacks so Hindi and Odia render correctly from the start. **[verify]** font availability through `next/font`.
- **Job UX:** a generation screen shows stage-level progress, survives navigation, and exposes retry. The user is never left on an indefinite spinner.
- **Secrets:** only `NEXT_PUBLIC_*` values reach the browser, and those are public by design.

## 12. Configuration reference

Authoritative tables for the Supabase variables, with defaults and where to find each value, are in [SUPABASE_SETUP.md §4](SUPABASE_SETUP.md#4-environment-variable-reference).

All configuration is environment-based and validated at startup (Pydantic Settings in the API; a Zod-validated module in the web app). Startup fails fast with a clear message listing missing or invalid variables, without printing secret values. `.env.example` files contain placeholders only; real `.env` files are git-ignored.

| Variable | Used by | Secret | Milestone | Purpose |
|---|---|---|---|---|
| `APP_ENV` | api, worker | No | M1 | `local` · `test` · `staging` · `production` |
| `APP_NAME` / `NEXT_PUBLIC_APP_NAME` | api, web | No | M1 | Configurable product name |
| `APP_VERSION` | api | No | M1 | Reported by `/healthz`; set from the release in deployed environments |
| `LOG_LEVEL` | api, worker | No | M1 | Logging verbosity |
| `CORS_ALLOWED_ORIGINS` | api | No | M1 | Comma-separated web origins; scheme + host only; `https` required in staging/production |
| `DATABASE_URL` | api, worker | **Yes** | M1 | Postgres connection (pooler; mode per §16) |
| `SUPABASE_URL` | api, worker | No | M1 | Project URL |
| `SUPABASE_JWT_MODE` | api | No | M1 | `jwks` or `hs256` |
| `SUPABASE_JWKS_URL` | api | No | M1 | JWKS endpoint (jwks mode); default `{SUPABASE_URL}/auth/v1/.well-known/jwks.json` |
| `SUPABASE_JWT_SECRET` | api | **Yes** | M1 | HS256 secret (hs256 mode only; at least 32 characters) |
| `SUPABASE_JWT_AUDIENCE` / `SUPABASE_JWT_ISSUER` | api | No | M1 | Expected `aud` (default `authenticated`) and `iss` (default `{SUPABASE_URL}/auth/v1`) |
| `JWT_LEEWAY_SECONDS` | api | No | M1 | Clock-skew tolerance for `exp`; default 10, at most 60 |
| `DB_POOL_MIN_SIZE` / `DB_POOL_MAX_SIZE` / `DB_POOL_TIMEOUT_SECONDS` | api | No | M1 | Connection pool; defaults 1 / 10 / 5 |
| `MAX_ACTIVE_GOALS_PER_USER` | api | No | M1 | Per-user goal cap; default 50 |
| `SUPABASE_PUBLISHABLE_KEY` | api, worker | No (public by design) | M6 | The project's publishable key, which Storage's gateway wants next to the learner's own token. **The service-role/secret key is not used anywhere** (ADR-040) |
| `NEXT_PUBLIC_SUPABASE_URL` | web | No | M1 | Auth client |
| `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` | web | No (public by design) | M1 | Auth client; the publishable key (`sb_publishable_…`) or a legacy anon key. Replaces the planned `…_ANON_KEY` name because Supabase is deprecating anon/service-role keys by the end of 2026 |
| `NEXT_PUBLIC_API_BASE_URL` | web | No | M1 | FastAPI base URL for the browser; compiled in at build time; required for production builds |
| `API_INTERNAL_BASE_URL` | web (server) | No | M1 | Address server-rendered pages use to reach the API (Docker: `http://api:8000`); defaults to the public URL |
| `LLM_PROVIDER` | api, worker | No | M3 | `gemini` · `openai` · `fake` (not allowed in staging/production) |
| `GEMINI_API_KEY` / `OPENAI_API_KEY` | api, worker | **Yes** | M3 | Provider credential |
| `LLM_MODEL_*` | api, worker | No | M3 | Model id per stage |
| `DOCUMENT_STORAGE`, `DOCUMENT_LOCAL_DIR`, `DOCUMENT_BUCKET` | api, worker | No | M6 | `supabase` (default) or `local` (development and tests only; refused in staging/production), the folder for `local`, and the bucket name (`documents`) |
| `DOCUMENT_MAX_BYTES`, `DOCUMENT_MAX_PAGES`, `DOCUMENT_MAX_CHARS`, `DOCUMENT_MAX_OCR_PAGES` | api, worker | No | M6 | One file (10 MB), its pages (300), the text taken from it (1,000,000 characters) and how many scanned pages may be read by the vision model (20) |
| `DOCUMENTS_PER_GOAL`, `DOCUMENTS_PER_USER`, `DOCUMENT_JOBS_PER_USER_PER_DAY`, `DOCUMENT_SIGNED_URL_SECONDS` | api | No | M6 | 20 / 100 / 100 / 3,600 |
| `EMBEDDING_MODEL` | worker, api | No | M6 | `gemini-embedding-001`; the vector size is fixed at 1536 by the column type |
| `CHUNK_TARGET_CHARS`, `CHUNK_OVERLAP_CHARS` | worker | No | M6 | Passage size (1,200) and overlap (200, less than half of the size) |
| `RETRIEVAL_TOP_K`, `RETRIEVAL_MIN_SIMILARITY`, `DOCUMENT_SEARCHES_PER_USER_PER_HOUR` | api, worker | No | M6 | Passages per search or lesson (6), the similarity bar (0.58) and searches a learner may run per hour (120) |
| `BUDGET_*_PER_USER_PER_DAY` | api | No | M3 | Generation limits (A8) |
| `WORKER_CONCURRENCY`, `JOB_LEASE_SECONDS`, `JOB_MAX_ATTEMPTS` | worker | No | M3 | Queue behaviour |
| `QUIZ_JOBS_PER_USER_PER_DAY`, `QUIZ_QUESTION_COUNT`, `QUIZ_SHORT_ANSWERS` | api, worker | No | M5 | Quizzes a learner may have written per 24 hours (30); questions per quiz (5, 3–10) and how many are short answers (1, at most 2) |
| `MASTERY_NEEDS_PRACTICE_BELOW`, `MASTERY_MASTERED_FROM`, `MASTERY_RECENCY_DECAY`, `MASTERY_MIN_ANSWERS` | api, worker | No | M5 | Mastery bands (70 / 90), how much an older attempt counts relative to the next newer one (0.7), and how many answers make a score more than an early estimate (4) |
| `LOG_LLM_PAYLOADS` | api, worker | No | M3 | Default `false`; never enabled in production |
| `YOUTUBE_API_KEY` | worker | **Yes** | M7 | Resource curator |
| `SENTRY_DSN` / `NEXT_PUBLIC_SENTRY_DSN` | api, web | No | M9 | Error tracking |

## 13. Security, privacy and threat notes

| Threat | Control |
|---|---|
| Broken object-level authorization (reading another user's goal, lesson, attempt) | Service-layer ownership checks + RLS in the request transaction + 404 on non-owned IDs + cross-user tests at API and database level |
| Answer-key exposure | Separate `question_answer_keys` table with no client-role grants; keys read only inside grading; response-shape tests assert the absence of key and explanation fields before submission |
| Forged or replayed tokens | Signature, `aud`, `iss`, `exp` checks; short-lived access tokens; clock-skew tolerance bounded |
| Session theft through cross-site scripting | Session cookies are `HttpOnly` and written only by the server; Supabase's browser client is not used, so no token is readable by page scripts; security headers (`X-Frame-Options`, `nosniff`, referrer policy) |
| Valid token for a deleted or locked-out account | Profile lookup in the request transaction fails closed with 401 `ACCOUNT_NOT_FOUND`; the sign-in page for `session_ended` shows the form instead of looping (ADR-024); access tokens are short-lived |
| Service credential leakage | Server-only env; no `NEXT_PUBLIC_` prefix on secrets; secret scanning in CI (the repository is public); `.env*` git-ignored |
| Prompt injection via uploaded documents or goal text | Delimited data blocks; "data not instructions" system prompt; the model has **no tools** and cannot act; outputs validated by code; IDs and paths from model output re-checked against the database |
| Malicious uploads | Size limit enforced while streaming; type decided from the bytes (signatures, text decoding), never the name or `Content-Type`; bucket size/MIME limits; parsing in the worker with page/character limits, pure-Python and without rendering; files re-validated against the stored SHA-256; no inline serving (attachment, `nosniff`); private bucket and a per-object signed link that is removed when the job ends |
| Reading another learner's documents through search | Every retrieval statement filters on `user_id` and `goal_id` in SQL, in addition to row security on the API's connection; tests cover the API, the worker's privileged connection, a forged owner in the call, and naming another learner's goal or document |
| A document that tries to take over the model ("ignore your rules…") | Passage text is escaped and fenced as data; the prompt says so; the model has no tools; citations must name supplied labels; identifiers, page numbers and "grounded" status come from code |
| Stored files outliving their document | Deleted with the document and with the goal (§6.5); the one gap, account deletion, is documented |
| Cost abuse / denial of wallet | Per-user budgets checked before any model call, rate limits, bounded retries, token ceilings, usage ledger |
| Duplicate/replayed submissions | Idempotency keys + database uniqueness |
| Information leakage in logs/errors | Structured logs exclude prompts, document text and tokens by default; generic error bodies with request ID |
| Cross-site request abuse | The API accepts only Bearer tokens, never cookies, so it is not exposed to CSRF; the web app's cookie-authenticated Server Actions rely on `SameSite=Lax` cookies plus Next.js's Origin/Host check for Server Actions; sign-out is a POST form; strict CORS allow-list |
| Supply chain | Lockfiles (`uv.lock`, `package-lock.json`), Dependabot, `pip-audit`/`npm audit` in CI |

Data-protection notes: documents and performance history are sensitive; minimise what is stored, support deletion including storage, and disclose that content is processed by the configured AI provider. Revisit before serving minors (assumption A9).

## 14. Testing, CI and observability

### Test strategy

| Layer | Tooling | Covers |
|---|---|---|
| Backend unit | pytest | Services, validators, scoring, scheduling, settings validation, JWT verification (with locally generated keys) |
| Schema/contract | pytest + Pydantic | DTOs, lesson/quiz/roadmap schemas, malformed-output rejection |
| Database | pytest against a real PostgreSQL 16 (ADR-022) | RLS per role, grants, constraints, deleted-account behaviour, guard tests that fail the build if a `public` table lacks RLS or exposes anything to `anon`; composite-FK ownership and answer-key isolation join in M5 |
| Backend integration | pytest: the real app in-process against that PostgreSQL, with real signed tokens | The auth matrix (valid, missing, malformed, expired, wrong algorithm/audience/issuer, anonymous), cross-user access, validation, pool isolation, failure handling; queue claim/lease/retry/idempotency from M3 |
| Genuine Supabase | pytest `tests/supabase_stack` against `supabase start` (CI only) | Real Supabase Auth tokens, the profile trigger on a real `auth.users` insert, RLS under Supabase's own roles, PostgREST cannot reach the tables, sign-out ends the session |
| AI evaluation | pytest with fixtures and `FakeProvider`/recorded outputs | Hallucinated citations, malformed output, duplicate questions, contradictory answer keys, incomplete syllabi, plan feasibility |
| Frontend | Vitest + Testing Library | Form validation, loading/error/empty states, navigation |
| End-to-end | Playwright (`apps/web/e2e`; against a genuine Supabase stack in CI) | Implemented through M2: sign up → onboarding → goal → reload → edit → pause/complete/reopen → archive/restore/delete → settings persistence → sign out → sign in → **user B gets 404 pages and 404 API answers for user A's goal**. Extended each milestone toward roadmap → lesson → quiz → feedback → resume. It also runs locally against a Supabase Auth stand-in (see DEVELOPMENT.md) |
| External | Marked and run separately | Real provider/YouTube calls; never part of the default CI path |

Rule carried from the source brief: **no claim of passing tests unless they were executed and their output observed.**

### CI (GitHub Actions, built in M1)

Jobs: **API** (ruff format/lint, pyright, pytest against a PostgreSQL service container) · **Web** (Prettier, ESLint, `tsc`, Vitest, the contracts drift check that regenerates the OpenAPI types and fails on any diff, production build, `npm audit`) · **Supabase stack** (`supabase start` applies every migration, then the genuine-stack API tests and the Playwright journey run) · **Docker** (build and boot the images) · **Secret scan**. CI is the **authoritative** environment for anything that needs the genuine Supabase stack, because the primary dev machine cannot run Docker (§15); the database tests also run locally against a real PostgreSQL. Until the `supabase-stack` job has been observed green, the genuine-Supabase claims in this document are unproven.

### Observability and cost

- JSON logs via `structlog`, with `request_id`, `job_id`, `user_id` (hashed or omitted where not needed), `stage`, `model_id`, `latency_ms`, token counts.
- `ai_usage_events` is the cost ledger; a view computes per-user and per-job spend.
- Sentry (or equivalent) for web and API from M9; earlier if cheap.

## 15. Development environment

### 15.1 Required tooling

Node 24 + npm workspaces · Python 3.14 via `uv` (`.python-version`, `uv.lock`) · Git · Supabase CLI (as an npm dev dependency) · Docker (for the local Supabase stack) · a Supabase account.

### 15.2 Findings on the primary dev machine (Windows 11 Home) — verified 2026-10-09

| Finding | Evidence | Consequence |
|---|---|---|
| **Smart App Control is on** and blocks unsigned native code it has no reputation for | `VerifiedAndReputablePolicyState = 1`; blocked-file errors observed | Native dependencies can fail to load. Test new native dependencies early; keep lockfiles; prefer pure-Python/pure-JS where equal. Do **not** disable the setting as a workaround. |
| Python **3.12.14** (uv-managed) cannot `import ssl`; its `psycopg` binary wheel is blocked | `DLL load failed … Application Control policy` | Do not target 3.12 here. |
| Python **3.14.7** (uv-managed) works: `ssl`, `httpx` HTTPS, `pydantic-core`, `cryptography`, `orjson`, `psycopg[binary]`, `asyncpg`, FastAPI, uvicorn all import and run | Imports and an HTTPS request succeeded | **Backend targets Python 3.14.** |
| Node natives load: `@next/swc`, `@tailwindcss/oxide`, `lightningcss`, `esbuild`, `rollup`. **`@swc/core` fails to load its native binding** (exact cause not captured; consistent with the policy above) | Loaded / failed under Node 24 | Do not depend on `@swc/core` (Next.js does not need it). |
| Supabase CLI runs when installed from npm (2.120.0) | `supabase --version` succeeded | Use it as a dev dependency. |
| **Verdicts change over time (observed 2026-10-10).** The venv launcher `services/api/.venv/Scripts/python.exe` and `ruff.exe`, both of which ran the day before, were blocked (`os error 4551`); recreating the venv did not help. The base interpreter, Node, Git and the `pgserver` PostgreSQL binaries still ran | Re-ran pytest and pyright through the base interpreter with `PYTHONPATH` pointing at the venv's site-packages: 250 passed, 1 skipped, 0 type errors | Do not assume a tool that worked yesterday works today. The fallback recipe is in DEVELOPMENT.md; `ruff` is verified in CI while it is blocked. Never disable the setting. |
| `LongPathsEnabled = 0` | Registry value | Keep the checkout path short (for example `C:\dev\StudyPilot`). `node_modules` will exceed 260 characters inside deep application-data folders. |
| **No Docker, no WSL, no `psql`, no `gh`, no `pnpm`** | Command lookups; `wsl` reports the component is not registered | The local Supabase stack **cannot run on this machine as-is**. See below. |
| `git` identity unset; Git defaults new repos to `master`; `core.autocrlf=true` | `git config` | The repo uses `main`, LF line endings via `.gitattributes`, and a per-repo identity. |

### 15.3 Running database-dependent work without local Docker

In order of preference:

1. **A real PostgreSQL without Docker (used since M1b)** — the `pgserver` wheel runs PostgreSQL 16 on Windows; the API tests apply the real migrations to it (ADR-022). It covers constraints, grants, RLS and the request-transaction pattern, but not Supabase's own Auth service.
2. **CI as the gate** — pgTAP, migration, drift, integration and E2E jobs run in GitHub Actions where Docker is available. Local work is limited to unit tests and linters.
3. **A hosted Supabase dev project** — the API and web app run locally against it; integration tests are opt-in (`RUN_INTEGRATION=1`) and use disposable test users. Never point tests at production.
4. **GitHub Codespaces / a dev container** (`.devcontainer/`, added in M1) — a Linux environment with Docker-in-Docker, giving the full local stack.
5. **Install WSL2 + Docker Desktop** — possible, but needs administrator action, and Smart App Control may block parts of it; treat as unproven until tried.

## 16. Deployment topology

| Piece | Host | Notes |
|---|---|---|
| Web | Vercel, project root `apps/web` | Preview deployments per pull request |
| API | Render web service from `services/api/Dockerfile` | Health check `/readyz` |
| Worker | Render background worker, same image, command `python -m app.workers` | Scale independently of the API |
| Database, Auth, Storage | Supabase managed | Separate projects for staging and production |
| Database connection | Supabase pooler in **session mode** for the long-lived API and worker | **Verified against Supabase's docs on 2026-10-10:** the shared pooler is IPv4-reachable on every plan (session mode on port 5432, transaction mode on 6543); direct connections are IPv6-only unless the IPv4 add-on is bought; transaction mode does not support prepared statements (the API's pool disables them). Whether Render has IPv6 egress is still to be confirmed at the M2 deploy skeleton. |

Environments: `local` → `staging` (preview/branch) → `production`. Migrations run in CI on merge: staging automatically; production after a manual approval. A **walking-skeleton deployment** (health endpoints plus the goals slice) happens at the end of M2 so deployment surprises appear early, not at the end.

## 17. Decision log

| ID | Decision | Alternatives considered | Rationale | Status |
|---|---|---|---|---|
| ADR-001 | Modular monolith; one Python package with API and worker entrypoints | Microservices; separate worker repo | Smallest operational surface; shared domain code | Accepted |
| ADR-002 | Supabase SQL migrations are the schema source of truth; no ORM-generated DDL (data access: ADR-021) | Alembic; ORM-generated DDL | RLS, grants, `auth` triggers and storage policies are SQL-native; avoids two migration systems | Accepted (amended by ADR-021) |
| ADR-003 | PostgreSQL-backed queue (`SKIP LOCKED`, leases) on `generation_jobs` | Redis + RQ/Arq/Celery; pgmq; Procrastinate | One durable store, transactional enqueue, no extra service; revisit on measured need | Accepted |
| ADR-004 | Browsers/mobile use Supabase for Auth only; all data via FastAPI; Data API not exposed for app tables | Direct PostgREST from clients | Keeps business rules and answer keys server-side; one API surface | Accepted |
| ADR-005 | Clients call FastAPI directly with a Bearer token; no Next.js BFF | BFF proxy in route handlers | Same contract for web and Expo; avoids a second API layer | Accepted (web amended by ADR-023) |
| ADR-006 | User requests run in RLS-scoped transactions (`SET LOCAL ROLE authenticated` + claims); a separate privileged session for worker and key reads | Service-role connection with manual `user_id` filters only | A forgotten filter cannot leak data | Accepted (S1: verified on PostgreSQL 16; genuine Supabase via the CI stack job) |
| ADR-007 | Answer keys and explanations live in `question_answer_keys` with no client grants | Same table with column privileges; views | RLS is row-level; separate table removes the leak path entirely | Accepted |
| ADR-008 | pgvector `vector(1536)`, HNSW cosine, hybrid FTS; `embedding_model` stored per chunk | Pinecone/FAISS; 768/3072 dims | Matches source schema; no extra service; safe model changes | Accepted (model **[verify]**) |
| ADR-009 | `LLMProvider` interface, schema-constrained outputs + Pydantic re-validation; Gemini adapter first, OpenAI second; `FakeProvider` for tests only | Provider SDKs called from business logic; LangChain-style frameworks | Swappable provider, deterministic tests, no framework lock-in | Accepted (provider order: assumption A4) |
| ADR-010 | Grading, mastery, SR scheduling and next-action are deterministic | LLM-as-judge for mastery | Reproducible, testable, no extra cost | Accepted |
| ADR-011 | OpenAPI is the contract; generated TS types + client; CI drift check | Hand-written client types; tRPC | Prevents drift; works for Expo too | Accepted |
| ADR-012 | Tooling: npm workspaces, `uv`, Python 3.14, Node 24, ruff, pyright, pytest, Vitest, Playwright, **TypeScript pinned to 6.0.x** | pnpm; Python 3.12; TypeScript 7 | `pnpm` isn't installed; 3.12 is blocked on the dev machine; `typescript-eslint` currently requires TypeScript below 6.1. **Verified in M1a:** TypeScript 6.0.3 with Next 16.4 and `typescript-eslint` 8.71.1 passes lint, type-check and build | Accepted (verified) |
| ADR-013 | Vercel (web) + Render (API, worker) + Supabase | AWS; Fly.io; Railway | Matches the source brief; lowest ops burden for an MVP | Accepted (accounts: user) |
| ADR-014 | Text extraction behind `TextExtractor`: `pypdf` for digital PDFs, vision-capable LLM for scans/handwriting; avoid AGPL libraries | Tesseract; PyMuPDF; cloud OCR | Handles handwriting best-effort without native binaries; permissive licences | Accepted — privacy implication documented |
| ADR-015 | One migration per slice, with RLS and pgTAP tests in the same change | One initial 17-table migration | Policies are only trusted when tested with their table | Accepted |
| ADR-016 | Errors as RFC 9457 problem+json; 404 for non-owned resources | Ad-hoc error shapes; 403 | Stable client handling; no ID enumeration | Accepted |
| ADR-017 | Jobs checkpoint per stage and resume on retry | Restart from scratch | Retries must not repeat or re-bill completed stages | Accepted |
| ADR-018 | Keep Next.js **Cache Components** and Partial Prefetching enabled (the `create-next-app` default). Anything per-request starts with `await connection()` under `<Suspense>`; live route handlers do the same | Disable Cache Components; opt out per route | It is the documented direction of Next 16 and supports streaming shells with dynamic data; dev mode surfaced the `Date.now()` rule immediately, so mistakes are loud | Accepted (verified in M1a) |
| ADR-019 | UI foundation: shadcn/ui with **Radix** primitives ("nova" style) copied into `components/ui` and adapted to our tokens; class merging via the shadcn-maintained `cn` package | Base UI primitives; Material/Chakra; clsx + tailwind-merge | Owned, accessible, minimal-dependency components; `cn` provenance verified on npm (maintainer and repository) | Accepted |
| ADR-020 | Python tooling is invoked as `python -m <tool>` (never the generated launcher executables); API entrypoint is `uvicorn app.main:create_app --factory`; the test-client dependency is `httpx2` | Console-script launchers; module-level `app = create_app()`; `httpx` | Smart App Control blocks the `pytest.exe` launcher that `uv` generates; `--factory` keeps imports free of side effects; Starlette 1.7 deprecates `httpx` in its TestClient in favour of `httpx2` (provenance verified) | Accepted (verified) |
| ADR-021 | Data access is psycopg 3 + `psycopg_pool` with explicit, parameterised SQL in repositories; row shapes are Pydantic models; no ORM | SQLAlchemy 2.x (the original plan); asyncpg | With user-scoped transactions and column-level grants the SQL *is* the design; there are no models to drift from the migrations; fewer moving parts; the role/claims pattern and pool isolation were verified under test (S1) | Accepted (verified) |
| ADR-022 | Database tests run in pytest against a **real PostgreSQL 16** (the `pgserver` wheel locally, a service container in CI) after applying a minimal stand-in for Supabase's roles and `auth` schema plus every real migration; a separate CI job repeats the essentials on a genuine `supabase start` stack. pgTAP is not used | pgTAP via `supabase test db`; PGlite; mocks | No Docker on the dev machine, and tests must run where the work is done. PGlite was tried and dropped (its socket multiplexer desynchronised after errors). The stand-in is a known risk; the genuine-stack job exists to cover it | Accepted (stack job unobserved until CI runs) |
| ADR-023 | The web app's session cookies are `HttpOnly` and written only by the server; Server Components and Server Actions call FastAPI with the token read server-side; Supabase's browser client is not used. Amends ADR-005 for the web: the API contract is unchanged and mobile will still call it directly with a Bearer token | Script-readable cookies (the library default); browser client with `localStorage` | An XSS bug cannot read the tokens, and the API accepts only Bearer tokens so it is not exposed to CSRF. Cost: no client-side Supabase features (realtime, direct uploads) without revisiting this | Accepted |
| ADR-024 | Route protection has three independent gates: the proxy (UX redirects), a server-side session check in every protected page, and token verification in the API. When the API rejects a session Supabase still holds, the user is sent to `/sign-in?…&error=session_ended`, which shows the form instead of bouncing them back | Proxy-only protection; clearing cookies in a GET handler | "Never rely on frontend-only protection"; the marker prevents the redirect loop that a deleted account or a key-mode mismatch would otherwise cause (found in review; covered by tests) | Accepted |
| ADR-025 | The goal lifecycle is enforced **twice**: the API's service layer gives friendly errors (`INVALID_STATUS_TRANSITION`, `GOAL_ARCHIVED`, `GOAL_NOT_ARCHIVED`), and the database refuses illegal states regardless (a trigger for transitions and archived read-only; checks tying `completed_at` / `archived_at` to the status; those columns are not in any client `UPDATE` grant; the delete policy matches archived rows only). Learner preferences (default minutes, languages, learning preferences, onboarding completion) are columns on `profiles`, and a goal created without them copies the profile's values | Application-only checks; a `user_preferences` table; storing preferences as JSON | A bug or a second client (the future mobile app) cannot corrupt a goal; deletion is a deliberate second step after archiving; a one-to-one table or a JSON blob would add a join or lose constraints for four small fields | Accepted (verified on PostgreSQL 16 and under Supabase's roles in CI run 38109598536) |
| ADR-026 | A page that `<Link>` can prefetch never redirects based on data it loads (for example "no onboarding yet → /onboarding"); it shows a prompt instead. Anything that builds a Supabase client first runs `await connection()` | Redirect from the dashboard to onboarding; a client-side check | Next's client router caches a redirect recorded during prefetch and replays it after later navigation, overriding a Server Action's own redirect (observed: the onboarding banner vanished, and a finished wizard bounced back). The Supabase auth client reads `Date.now()` when constructed, which Cache Components rejects at prerender | Accepted (found and reproduced in the browser; covered by the Playwright journey) |

| ADR-027 | Gemini is called over its **REST API** with the project's own HTTP client, not through `google-genai`. Structured output uses `generationConfig.responseMimeType = application/json` with `responseJsonSchema` (a reduced JSON Schema). Google's docs page shows a `responseFormat.text` shape instead, but the live API rejected it (400 on the mime-type enum) and accepted these two fields, so the adapter was corrected against the live API; the key travels in the `x-goog-api-key` header, never in a URL. Our Pydantic models are converted to the documented subset of JSON Schema (`$ref`s inlined, unsupported keywords dropped), and every reply is re-validated against the real model. Default model `gemini-3.6-flash` (chosen after timing the same request on three models: 6 s / 18 s / 96 s for 3.5-flash-lite / 3.6-flash / 3.8-flash), configurable. `maxItems` is not sent: the live API answered a bare 400 for the roadmap schema until it was removed; the Pydantic model still enforces it | `google-genai` SDK; the legacy `responseSchema` / `responseMimeType` fields; free-form JSON parsing | The request is small and stable, easy to test with a mock transport, adds no dependency that Windows Smart App Control could block, and keeps the key out of logs. Request shape and model ids were read from Google's docs on 2026-10-11 and then probed against the live API with the owner's key (the docs describe both `generateContent` and a newer Interactions API; `generateContent` is documented as fully supported) | Accepted (request shape confirmed live; plan quality still to be read by a person) |
| ADR-028 | The worker uses a **privileged database session** (`Database.system_session()`): the pool's own role, which bypasses Row Level Security, because it must claim jobs of every user. It exists only for `app/jobs` and `app/worker.py`, is a distinct type (`SystemConnection`), filters by `user_id` explicitly, and a test fails the build if request-serving code (`api`, `services`, `repositories`, `schemas`) mentions it. The Supabase service-role key is still not used | `SECURITY DEFINER` functions for every worker write; the service-role key | One audited place for cross-user work; the learner-facing code path keeps its "RLS cannot be bypassed by a forgotten filter" property | Accepted |
| ADR-029 | **A roadmap is immutable and versioned.** Regenerating or revising never edits a plan: the worker stores the next version (`unique (goal_id, version)`), the previous current one becomes `superseded`, and the learner can make any version current again. Clients can change only `status`; archived goals cannot switch versions; one roadmap per job makes retries exactly-once | Overwrite in place; a draft-then-accept step; a diff view | "Updates must not silently destroy the user's plan"; history costs a few rows. A draft/accept step was left out to keep the first slice small: the new version is current at once but the old one is one click away | Accepted |
| ADR-030 | **The planner's plan is checked by code, never by asking the model.** One call produces a plan; `validate_plan` checks the daily minutes per day (topics and revision together), the horizon before the target date, prerequisite existence and order (which also rules out cycles), day order, objective coverage both ways, revision timing, language, unique keys, evidence references and "unknowns required for exam goals without an official syllabus". Identifier formatting is normalised in code. Failures go back to the model **once** with the full list; a second failure ends the job as `PLAN_INVALID`. Totals shown to the learner are computed from the stored items | Trusting the model's own totals; unbounded repair loops; a second model as judge | Plans must be feasible for this learner; cost must be bounded; validation must be testable without a model | Accepted |
| ADR-031 | The confirm route accepts **both** kinds of email-confirmation link: `?token_hash=…&type=…` (custom template, any device) and `?code=…` (Supabase's built-in template, PKCE, same browser only). The proxy forwards a bare `/?code=…` on the landing page to `/auth/confirm?code=…&next=/onboarding` and nothing else from that query; a code must match a strict charset/length before it is ever sent to Supabase. When a code cannot be exchanged the person is told their address is confirmed if they followed the link, and asked to sign in | Require the custom template; ignore `?code=` | The hosted project used the built-in template, so the email link confirmed the account but dropped people on the home page signed out. Not trusting a code that has no matching verifier cookie is what PKCE is for; a malicious link cannot sign anyone in as someone else | Accepted (unit-tested; the email link itself cannot be exercised in CI) |
| ADR-032 | **A lesson is a typed, versioned, immutable document, written only by the worker.** The model fills in a flat `DraftLesson` (one `type` per block and the fields that type uses: no `oneOf`, no nulls, which every provider accepts); code turns it into the strict `Lesson` (blocks are a discriminated union: paragraph, list, code, callout; section ids are assigned by code) and that is what is stored, validated again on every read, and sent to the browser as a typed contract. A new version is a new row; earlier ones are kept. A lesson job may only name a topic of the learner's current roadmap (database trigger), at most one is active per topic (unique index), and one lesson is stored per job (unique key) | A markdown string; free-form blocks; editing a lesson in place; model-written section ids | "Do not treat lesson content as an arbitrary unvalidated string"; a typed document renders without any path from model text to HTML; versions make "write it again, simpler" safe | Accepted |
| ADR-033 | **A lesson is checked by code, with one repair, and says where its content comes from.** `build_lesson` rejects empty blocks and sections and reports anything that does not fit the stored limits by *where* it is (never by quoting it); cosmetic overruns (a callout title, a caption, an analogy) are trimmed instead of costing a second call. `validate_lesson` checks the language, duplicate headings, thin sections, a word budget from the topic's minutes, web addresses and DOI/ISBN in the prose, citations (every `source_id`/`chunk_id` must be one that was supplied; none exist before M6, so any is rejected) and a simple explanation that merely repeats the summary. Failures go back **once**; a second failure ends the job as `LESSON_INVALID`. A lesson with no sources says on screen that it is written from general knowledge | Asking the model whether its lesson is good; stripping invalid citations silently; unbounded retries | "Avoid unsupported claims and fabricated citations" has to be enforceable without a model; cost must be bounded; a lesson must never look more authoritative than it is | Accepted |
| ADR-034 | **"Explain simply" re-explains the lesson, never new material.** Every lesson is written with a `simple_explanation` (everyday words, one analogy) in the same call, so the action shows stored content at once and needs no model. For a deeper rewrite the learner asks for a new version with `adjust` = `simpler`, `more_examples` or `deeper` (and an optional note, 300 characters, fenced as data); the job is given the *existing lesson* and told to keep the topic and objectives. The earlier version stays readable | A model call on every click; a separate "ELI5" table; free-form rewriting | Instant, free and reliable for the common case, grounded by construction; the rewrite path reuses the queue, limits and versions | Accepted. A separate "Explain like I'm five" level is not built |
| ADR-035 | **Study progress belongs to a lesson version and is written with the learner's own identity.** `lesson_progress` is written through the request transaction (row security), not by the worker, and the database refuses unknown or repeated sections, a `completed` lesson with sections left, and any write once the goal is archived. The reader saves the section being read (the last one whose top has passed a reading line, measured on scroll so a jump to the end counts) a moment after the learner stops, and a section tick or finish at once, through a Server Action (the token never reaches the browser); reopening scrolls back and offers to continue or start again. A topic is *done* if any version of its lesson was finished. Limits: one lesson job per topic, at most two in flight per learner, 60 a day (configurable) | Browser-held progress; saving every scroll event; progress per topic only | Progress must survive devices and reloads and must not be forgeable; a new version of a lesson legitimately starts fresh | Accepted |
| ADR-036 | **Grading, mastery and the next step are deterministic code over stored answers, and the answer key is read in exactly one place.** `app/grading` is the only code that reads `question_answer_keys` (an architecture test enforces it, and that request code cannot even name the table). It runs in one privileged transaction given only the caller's identity and what they submitted: the submission is checked against the quiz's own questions first (unknown question, duplicate answer, option that is not one of the question's, wrong kind of answer are all refused before a key is read), multiple-choice and true/false are graded by comparing option ids, and the right answer, explanation and rubric are **copied into the learner's own answer row** at that moment, so nothing is revealed earlier and reading results never touches the key table again. Mastery is a recency- and difficulty-weighted score (see §8.4) stored as a recomputable cache with `algorithm_version`; the band and "early estimate" flag are derived from today's thresholds at read time; the recommendation is an ordered pure function. A low score yields a targeted practice quiz on the weakest objectives (chosen by the server from stored answers, never by the client), not a restart | Model-judged mastery; reading keys with a policy; a stored band; letting the client pick the practice focus | Reproducible, testable, no extra cost (ADR-010); one place to audit for leaks; a threshold change applies to every stored result without a migration | Accepted |
| ADR-037 | **Marking free text is an estimate, and the learner has the last word.** The rubric (2–5 checkable points) is written with the question and kept in the answer key, so the marker is asked a narrow question per point rather than "is this good". A model only says which rubric points an answer clearly makes; the points are **added up by code**, so a score can never exceed the rubric, and the reply must name each answer once and only real rubric points (one repair, then `GRADING_INVALID`). The learner's text is escaped and fenced as data. Marking is a background `grade` job (retry limited to four per attempt; a failure leaves the answers `pending`, never guessed). Results label it **AI estimate**, show the rubric and a model answer, and let the learner tick which points they really covered; that review (`self_review`) replaces the estimate, the points are recomputed on the server from the rubric (a client never sends points), and the attempt totals and the topic's mastery follow. A review made while a job waits is never overwritten by the job | Letting the model score directly; hiding that it is a model; no way to dispute | Honest about what a model can do on open text, bounded in cost, and consequential assessments stay reviewable | Accepted |
| ADR-038 | **A quiz is taken once; practising again means a new quiz.** One quiz is written per lesson version by a `quiz` job (a lesson must exist: `LESSON_REQUIRED`), a topic holds at most one untaken quiz (`QUIZ_PENDING`) and one active quiz job, and `unique (quiz_id)` on attempts makes a second submission a 409 (`QUIZ_ALREADY_SUBMITTED`) while an `Idempotency-Key` returns the same attempt. A new quiz is told the earlier questions (never their answers) so it does not repeat them, and a code check rejects near-duplicates of earlier prompts. Attempts, answers and mastery are written only by the grader and worker, so clients cannot forge a score. The built-in test provider's quizzes carry `is_synthetic` and are labelled samples; the sample banks carry on through each bank so a long run never repeats a question | Re-takeable quizzes with the same questions; client-written attempts | Retaking the same questions measures memory of the answers, not understanding; forged attempts would corrupt mastery | Accepted |
| ADR-039 | **What a file is comes from its bytes, and extraction is pure-Python, bounded and non-rendering.** `detect` accepts a PDF (signature within the first 1,024 bytes), PNG, JPEG, WebP, or text that decodes as UTF-8 or UTF-16 with almost no control characters; the extension must agree with the content (a program renamed `.pdf` and a PDF renamed `.txt` are both refused) and the browser's `Content-Type` is ignored. The size is enforced while the body streams. Text is taken from PDFs with `pypdf` (no PyMuPDF: AGPL) up to a page and a character limit; encrypted or damaged files fail with a message a learner can act on. The worker repeats the checks against the stored SHA-256 and signature because the bytes came from storage | Trusting the extension or `Content-Type`; a rendering library; unbounded extraction; a malware scanner now | "Validate file signatures, restrict file size and type, use safe extraction libraries"; a public repository and public sign-up make the parser the attack surface, so keep it small and bounded | Accepted. Malware scanning stays a recorded risk acceptance |
| ADR-040 | **Files live in a private Supabase Storage bucket, reached with the learner's own token; the worker reads through a one-object signed link. The service-role key is not used.** `{user_id}/{document_id}/{safe name}` in the `documents` bucket (private, 10 MB, a MIME allow-list); Storage's row security (a migration) lets an authenticated learner select/insert/delete only objects whose first folder is their own id, and there is no update policy, so an object is never overwritten. The API forwards the learner's access token (plus the publishable key) to Storage to upload, download and delete, and asks it for a signed link per job; the link goes in the job's `request` and is removed when the job ends. Downloads are proxied by the API as attachments. A `LocalFiles` store serves development and tests and is refused in staging/production. The bucket and its policies are created only where Storage is installed (a fresh local stack without the storage service has none) | The service-role key in the API and worker; public buckets; signed upload URLs from the browser; storing files in the database | CLAUDE.md forbids the secret key without a recorded decision; a per-learner prefix policy gives the same isolation without it; the browser never needs a storage URL | Accepted. **Supabase Storage itself is verified only on a mock transport**; the real-stack tests skip where Storage is absent (CI's stack excludes it) |
| ADR-041 | **Retrieval is exact, hybrid and scoped in SQL, and "nothing found" is an answer.** See §6.4. Cosine distance and full-text rank over one learner's one goal are fused with reciprocal rank fusion; a similarity bar decides what counts; no ANN index until measured; the operator is schema-qualified. The API embeds the question (rate-limited per learner in memory) and searches inside the learner's own transaction; the lesson job searches with the privileged connection and an explicit filter | An HNSW index with post-filtering; semantic only; always returning the top k | Filtered ANN search silently returns too few rows; exact search at this scale is simple and correct; always returning something invites fabricated support | Accepted. The bar (0.58) comes from one live sample (4 passages x 4 questions, gemini-embedding-001) and is a starting point to calibrate on real material; a passage that shares a word with the question needs 85 % of it |
| ADR-042 | **Pictures and scans are read by a vision model, and anything uncertain waits for the learner.** A page with no text layer, or an image, is sent (one page at a time) to `read_image_text`, which returns the text and a legibility (`clear`, `partly`, `poor`, `none`). Only all-`clear` readings go straight to indexing; otherwise the document is `review`: the pages are shown, editable (a trigger allows edits only in that state), and nothing is searchable or cited until the learner confirms. At most `DOCUMENT_MAX_OCR_PAGES` pages per document; reading failures degrade a mixed PDF with a warning and fail a scan-only one with a clear reason. What the model read is stored as data and is never treated as instructions | Indexing OCR output silently; a separate OCR engine (a native dependency the dev machine may block); trusting the model's confidence without a gate | "For uncertain handwriting recognition, allow users to inspect extracted text before relying on it"; the cost of a wrong passage is a wrong lesson | Accepted. Handwriting quality is unmeasured |
| ADR-043 | **Document processing is one durable job with two tasks, atomic writes and a guaranteed final state.** `extract` reads the file, stores the pages and either continues to indexing or stops in `review`; `index` (after a review, or a retry of a failed indexing) embeds the stored pages. Pages and passages are *replaced* in one transaction that also ends the job, so a retry or a reprocess never duplicates and a crash leaves the previous state. One active job per document (unique index); a document cannot be deleted while it is processing; the runner marks the document failed when its job fails for good or is cancelled, and the reaper settles documents whose job ended without saying so, so a document never waits for a job that is gone | Several job types; incremental page-by-page commits; trusting the worker to always update the document | Exactly-once effect on retry, honest status, no zombie "processing" rows | Accepted |
| ADR-044 | **A grounded lesson cites labels that code resolves to real passages; groundedness is decided by code.** The writer is given the retrieved passages as `source_material` with labels (`S1`, `P2`), never ids or pages. Validation rejects an unknown label and any page number in the prose (the model was never told one); code replaces the labels with the real document and passage ids, drops anything else, and sets `grounding`: `sources` (it cites retrieved passages), `no_match` (the learner has documents but none matched, or none was cited) or `none`. A lesson with `no_match` says on screen that it comes from general knowledge. Citations are resolved when a lesson is read, so deleting a document leaves the lesson's words but shows its citation as unavailable and keeps no copy of the text. The prompt is `lesson-writer/v2`; `v1` lessons keep their version string | Asking the model for page numbers or document ids; storing excerpts in the lesson; failing the job when nothing is cited | "Return citations that point to actual retrieved passages. Never invent source IDs or page numbers. If evidence is insufficient, disclose the limitation"; retention requires that a deleted document leaves no content behind | Accepted |
| ADR-045 | **Embeddings are 1536-dimension unit vectors from one recorded model.** Gemini `gemini-embedding-001` is asked for `outputDimensionality` 1536 and the vectors are scaled to length 1 in code (a reduced-dimension vector is not unit length), with document and query task types. The column type enforces the size, each chunk records its model, and the worker checks count, size and model consistency before it writes. Changing the model means re-embedding and a new `embedding_model` value, not a schema change. The built-in test provider embeds with a deterministic bag-of-words hash (labelled synthetic; refused in staging/production) so the whole pipeline is testable without a model | A larger native dimension; a second vector column; embedding per request on the fly | Fixed dimension before any index; cosine and dot product agree on unit vectors; deterministic tests | Accepted. A live call to the embeddings endpoint was probed, not run on a real document |
| ADR-046 | **A spent daily allowance is not "busy": it is its own error, and other models take over.** Google's free tier allows about 20 generation requests per model per day. A 429 that names a per-day quota is `AI_QUOTA_EXHAUSTED` (`LLMQuotaExhausted`, not retryable, with the hours until it resets in the learner's message); any other 429 stays `AI_RATE_LIMITED` and is retried using the service's `RetryInfo`. `GEMINI_FALLBACK_MODELS` (comma-separated, validated) lists further models: when one answers quota, rate-limit or unavailable, `GeminiProvider` benches it for the advertised delay (at most a day) and asks the next one, and raises the original error only when every model is benched. The model that answered is what the usage ledger and the stored plan or lesson record. `GEMINI_THINKING_LEVEL` (`minimal`/`low`/`medium`/`high`, empty = the model's default) is sent as `thinkingConfig.thinkingLevel`: thinking tokens come out of the same output budget as the answer, so a high level makes long structured documents slow and can cut them off (`MAX_TOKENS`); a model that rejects the level is asked without it from then on. A lesson block that came back empty is dropped instead of failing the lesson (an empty *section* is still reported). | Telling the learner "busy" and retrying (it cannot succeed until the allowance resets); one model only; a paid tier as a requirement | A run on a real document showed lessons failing with a misleading message once the daily allowance was spent, and a document failing because a per-minute limit threw away the batches already embedded | Accepted. Quota, fallback and the thinking level are tested on a mock transport; the error shapes and the level's acceptance per model were observed against the live API |
| ADR-047 | **The roadmap is planned from the learner's own documents when there are any.** The worker reads where each stored passage sits (document, section heading, pages; no passage text, no model call) for the goal's `ready` documents only (at most 5; at most 70 sections after merging the smallest into their neighbour; a line that is not a heading is folded into the section before) and the planner is given that contents list as `uploaded_material` with labels (`S1` for a document, `C3` for a section) inside the `<learner_data>` fence. Prompt `roadmap-planner/v2` tells it to follow the sections, group and split them, cite the sections it used under `evidence`, set `syllabus_basis` to `uploaded_document`, and, for a test or exam with little time, make every practice task a self-test. Code checks the answer: a cited label must exist (`EVIDENCE_UNKNOWN`), a plan built from material must cite some and say so (`EVIDENCE_REQUIRED`, `BASIS_UPLOADED`), and a page number in the text must exist in the material (`PAGE_UNKNOWN`). Before storing, `ground_evidence` swaps the labels for the real document id and the section's first passage id (`app/ai/roadmap/material.py`). The material is the learner's notes, not an official syllabus: an exam goal still lists what could not be verified. Each topic's lesson then retrieves its own passages as before (ADR-044). | Sending whole documents or a model-written summary to the planner (cost, and the summary would be unchecked); asking the model for page numbers; planning only from the goal text | A roadmap that ignores the learner's textbook cannot be the plan for a class test on it; headings are already stored, so the contents list is free and checkable | Accepted. Checked with the built-in test provider and a real database; a live Gemini plan from a real document has not been judged by a person |
| ADR-050 | **Flashcards are written by the learner and scheduled by the server with a versioned, deterministic, SM-2-style rule (`sm2-v1`).** `app/learning/scheduling.py` is pure (no clock, no database): the card's schedule, the learner's rating (`again`, `hard`, `good`, `easy`) and the time give the next schedule (`again` is back in 10 minutes and resets the run; the first success is 1 day, the second 6, then the interval times the ease factor; `easy` goes 30% further than `good`, `hard` grows by 20%; intervals are capped at 365 days and the ease stays within 1.30 to 3.50). The browser sends only a rating and an `Idempotency-Key`; the API locks the card, computes the change, updates it and appends a review recording the schedule before and after and the scheduler version, in one transaction, so a double click counts once and history can be replayed under a different algorithm. A learner may write their own schedule columns (it affects nobody else and nothing is graded from it); the history is append-only and `reviewed_at` is not writable, so it cannot be backdated. Archived goals are read-only, a goal holds at most 500 cards, and another learner's card is a 404. Schemas are named `Flashcard*` because a clash with the quiz schema names once silently renamed an existing contract entry. | Letting the browser send the new due date; FSRS or a tuned model (no data to tune it on); storing only the current schedule (no replay); making the schedule server-only through a privileged session (adds a second writer for no protection that matters here) | A rule of thumb everyone can explain, tested over every reachable state, and a history that keeps the option of a better algorithm later. It is a heuristic, not validated learning science | Accepted. Database (30), scheduler (19) and API (41) tests run locally against PostgreSQL 16; the web is covered by unit and component tests, not yet exercised in a browser against a genuine Supabase stack |
| ADR-051 | **When Gemini cannot answer, other providers that speak the OpenAI chat format can; embeddings never move.** `LLM_FALLBACKS` is one secret JSON list (name, base URL, key, models, optional output limit and response format; `app/ai/fallback_config.py`, errors name entries and fields and never a value). `OpenAICompatibleProvider` (`app/ai/openai_compat.py`) posts to `{base}/chat/completions` with the key in the `Authorization` header, asks for the most specific response format the entry allows and steps down (schema, JSON object, plain prompt with the schema in the text) when a provider refuses one, cuts the reply down to its JSON object (reasoning blocks and fences removed), validates it against the same Pydantic model, and maps statuses to the same typed errors as Gemini (a 429 naming a per-day limit, or a 402, is `AI_QUOTA_EXHAUSTED`; its `Retry-After` or "try again in 7m" is kept). `ProviderChain` (`app/ai/chain.py`) asks Gemini first and only on quota, rate-limit or unavailable asks the others in order; `Bench` (`app/ai/bench.py`) rests a candidate for the time it says (a minute if it does not, at most a day) so no request is spent rediscovering that it is spent, and a candidate set up wrongly (bad key, unknown model) rests an hour and is logged, never shown to the learner. When nobody can answer, the error that clears first is raised with its wait. Anything else that goes wrong with Gemini (rejected key, blocked content, malformed answer) is its own error as before. Embeddings and reading pictures never fall back: every vector comes from one recorded model (ADR-045). The result records which provider and model wrote it. Off unless `LLM_FALLBACKS` is set. | Replacing Gemini; a hosted gateway such as OpenRouter as the only path; one adapter per provider; letting any provider embed | The free tier is about 20 requests per model per day, so a long session ends; the other free tiers are separate allowances behind one protocol, so a new provider is configuration, not code | Accepted. Tested on a mock transport (request shape, every status, response-format step-down, model and provider resting, error choice) and through the settings and factory; **no live call to a fallback provider has been made** (it needs the owner's key). Learner text, including passages of uploaded documents, is sent to every provider in the list: a privacy decision for the operator, see assumption A38 |

## 18. Deviations from the source brief

| Source brief | This design | Why |
|---|---|---|
| `correct_answer_json` and `explanation` on `questions` | Separate `question_answer_keys` table | RLS is row-level; same-table keys would be readable with the question |
| Child tables carry `user_id` by convention | Composite FKs `(parent_id, user_id)` | Database-enforced ownership across parent-child relationships |
| `questions` and `quiz_answers` have no `user_id` | Added | Simple, indexable RLS; consistent ownership model |
| `parent_item_id … on delete set null` | `on delete cascade` | Avoid orphaned child items |
| No place to store prerequisites | `roadmap_item_prerequisites` | FR-3 requires prerequisite ordering |
| `generation_jobs` lacks lease/retry/stage columns | Added | Required for durable queue semantics and checkpointed retries |
| `unique (user_id, idempotency_key)` | Partial unique index on non-null keys | Intent is explicit; null keys do not conflict |
| No usage ledger | `ai_usage_events` | Budgets (FR-10) and cost-per-learner metric |
| `goal_type` default `'skill'` | Vocabulary aligned with `LearningGoalSpec` | The source schema contradicted its own intent parser |
| One initial migration with all entities | One migration per slice | Tests accompany each table |
| Document upload P0 (Part II) vs P1 (master prompt) | P1, but required for the beta gate | Reconciles the two priority lists |
| `packages/design-tokens` | Deferred until Expo | YAGNI |
| Backend with service-role access | RLS-scoped request transactions + privileged session | Defence in depth |
| PostgREST available by default | Not exposed for application tables | One API surface; keys stay server-side |
| Python version unspecified | Python 3.14 | The only version verified to run the stack on the dev machine |
| SQLAlchemy models with a CI drift test | psycopg 3 and explicit SQL (ADR-021) | No models means nothing to drift; fewer layers between a request and its RLS-scoped transaction |
| pgTAP tests beside each migration | pytest database tests against a real PostgreSQL (ADR-022) | They run on the machine where the work is done, with the same code path as production |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` | Supabase is replacing anon/service-role keys with publishable/secret keys (legacy keys deprecated by the end of 2026) |
