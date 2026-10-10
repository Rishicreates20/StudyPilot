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
| `profiles` | M1 | `id` = `auth.users.id`. Created by an `after insert on auth.users` trigger (security definer) plus a backfill. |
| `learning_goals` | M1 | `goal_type` constrained to the intent-parser vocabulary (`exam`, `academic_subject`, `professional_skill`, `certification`, `interview`, `general`) — the source schema's default `'skill'` did not match its own `LearningGoalSpec`. `current_level` includes `unknown` so a guess is never stored as fact. Length and range checks on title, `daily_minutes` and `preferred_languages`. |
| `generation_jobs` | M3 | Source columns **plus** queue columns: `stage`, `progress jsonb`, `priority`, `run_at`, `locked_by`, `locked_until`, `max_attempts`, `cancel_requested`, `last_error` (sanitised). Idempotency is a **partial unique index** on `(user_id, idempotency_key) where idempotency_key is not null`. |
| `ai_usage_events` | M3 | **New.** One row per model/embedding call: job, stage, model id, prompt version, tokens in/out, latency, estimated cost. Drives budgets (FR-10) and the cost-per-learner metric. |
| `roadmaps` | M3 | `job_id` unique (one roadmap per job → retries cannot duplicate). Partial unique index: at most one `published` roadmap per goal. `unique (goal_id, version)`. |
| `roadmap_items` | M3 | Composite FK `(roadmap_id, user_id)` (see §6.3). `parent_item_id` uses `on delete cascade` (source used `set null`, which orphans children). Adds `topic_key` (links items to mastery) and, in M4, `last_section_index` / `last_studied_at` for resume. |
| `roadmap_item_prerequisites` | M3 | **New.** `(item_id, prerequisite_id)` join table, no self-reference. The source brief requires prerequisite modelling but its schema had nowhere to store it. |
| `learning_materials` | M4 | Lessons as validated JSONB (`content_json`), `citations_json`, plus `prompt_version` and `model_id` for traceability. |
| `quizzes` | M5 | As in the source brief. |
| `questions` | M5 | Prompt, options, difficulty, `objective_id`, `topic_key`, `position`. **No answer key, no explanation.** |
| `question_answer_keys` | M5 | **New.** `question_id` PK, `correct_answer_json`, `explanation`, citations. **No grants to `anon`/`authenticated`**; read only through the privileged session at grading time (ADR-007). The source schema put the key beside the prompt, and RLS is row-level, so a policy that lets a learner read their own questions would also have let them read the answers. |
| `quiz_attempts`, `quiz_answers` | M5 | `user_id` added to `quiz_answers` (the source had none). `unique (attempt_id, question_id)` retained. |
| `topic_mastery` | M5 | As in the source brief; recomputed deterministically from attempts. |
| `source_documents`, `document_chunks` | M6 | Chunks add `embedding_model`, a generated `tsvector` column with a GIN index for hybrid search, and `user_id` for retrieval-time filtering. |
| `flashcards`, `flashcard_reviews`, `learning_resources` | M7 | As in the source brief. |
| `content_reports` | M7 | **New.** Learner reports of incorrect lessons, questions or resources (FR-18). |
| `exports` | M8 | As in the source brief. |

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

### 6.4 Vectors and search (M6)

- `document_chunks.embedding` is `vector(1536)` with an HNSW index (`vector_cosine_ops`). Dimension and model are fixed *before* the index is built; changing them means re-embedding the corpus, so each chunk records `embedding_model` and queries filter on the current model. **[verify]** that the operator class must be schema-qualified when the extension lives in the `extensions` schema.
- Retrieval is hybrid: vector similarity combined with Postgres full-text rank (reciprocal rank fusion), always filtered by `user_id` (and the selected documents) **inside the SQL**, never by post-filtering.
- No separate vector database until measured latency, volume or isolation needs justify one.

### 6.5 Deletion and retention

- Deleting a `profiles` row cascades to all user data. Storage objects are **not** removed by database cascades, so account deletion is a worker job that deletes the user's storage prefix, then the auth user. Designed in M1 (so FKs are right), implemented and tested in M9.
- Retention windows for job payloads and logs are configuration, defaulted conservatively, and documented in M9.

## 7. Job queue

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

### 8.2 Workflow stages

Deterministic orchestration, not autonomous agents. A job type selects which stages run; text-only roadmap generation runs without retrieval or YouTube.

| # | Stage | Uses LLM | Input → output | Validation (by code) |
|---|---|---|---|---|
| 1 | Intent parser | Yes (small) | Goal form + free text → `LearningGoalSpec` | Schema; must not invent dates, levels or syllabus; unknown stays `null` |
| 2 | Document retrieval | No | Spec + user's chunks → evidence set | Ownership filter in SQL; empty evidence is a valid result (M6) |
| 3 | Curriculum planner | Yes | Spec + evidence → `Roadmap` | **Programmatic**: total minutes vs budget, prerequisite DAG is acyclic and ordered, every objective covered, unique sequence. One bounded repair attempt with the violations fed back; otherwise fail `PLAN_INVALID` |
| 4 | Lesson generator | Yes | One roadmap item + evidence → `Lesson` | Schema; every citation ID ∈ retrieved chunk IDs; no empty sections; unsupported source claims rejected |
| 5 | Assessment generator | Yes | Item + lesson → questions | Exactly one correct option; unique option IDs; objective ID exists on the item; duplicate detection; explanation present; keys stored separately |
| 6 | Resource curator | No (tool) | Topic + languages → ranked videos | Results come only from the YouTube API; cached; `last_verified_at` set (M7) |
| 7 | Quality gate | No | All stage outputs → pass/fail with reasons | Aggregates validators; failure never persists partial content as published |
| 8 | Persist & complete | No | Validated output → rows | Single transaction; keyed for exactly-once effect |

Lesson and quiz generation operate on **one roadmap item at a time**, never an entire curriculum in one request.

### 8.3 Prompts

- Stored in `app/ai/prompts/<stage>/vN` as versioned templates. The prompt version, model id and generation settings are recorded on every output (`learning_materials`, `ai_usage_events`).
- Learner text and extracted document text are inserted only inside clearly delimited **data** blocks, and the system prompt states that such content is reference data and never instructions (prompt-injection posture, §13).
- Prompt changes are reviewed like code and covered by the evaluation fixtures (§14).

### 8.4 Deterministic learning logic (ADR-010)

- **Grading.** Objective questions are graded by code. Short-answer grading, if ever added, uses a transparent rubric and is clearly marked as model-assisted.
- **Mastery.** Per `(user, goal, topic_key)`: a recency- and difficulty-weighted score over stored attempts. Thresholds (default: below 70 → remediate; 70–90 → progress; above 90 → schedule revision) are configuration, not model output, and are documented as tunable product rules.
- **Spaced repetition.** SM-2-style scheduling from the `flashcards` columns (`ease_factor`, `interval_days`, `repetitions`, `lapses`), with every review stored in `flashcard_reviews` so the algorithm can be replaced (for example by FSRS) without losing history.
- **Next action.** A pure function of mastery, due reviews and roadmap position. No extra model call.

## 9. Documents and retrieval (P1, M6)

1. **Upload.** The API creates a `source_documents` row and returns a signed upload URL for a private bucket (`{user_id}/{document_id}/{safe_name}`), or accepts the upload directly if the signed-URL flow proves unsuitable. Bucket limits (size, MIME types) are the first guard. **[verify]**
2. **Complete.** The client confirms; a worker job re-validates ownership, size and **file signature (magic bytes)**, then extracts. Filenames are normalised; originals are never served back inline.
3. **Extract.** Digital PDFs and text via `pypdf` (permissive licence; PyMuPDF is avoided because of its AGPL licence). Scanned pages and images go through a vision-capable model behind a `TextExtractor` interface (ADR-014). Extraction warnings and per-page confidence are kept; OCR text is reviewable and correctable before it is treated as authoritative.
4. **Chunk.** Overlapping chunks that respect headings and paragraphs, with document, page, chunk index and section metadata.
5. **Embed and index.** Batched, with usage metered; rows written with `embedding_model`.
6. **Retrieve.** Hybrid search scoped to the user (§6.4); optional rerank later.
7. **Cite.** The lesson validator rejects any citation not in the retrieved set. When evidence is insufficient the lesson says so rather than inventing support.

Malware scanning (for example ClamAV) is not in the MVP; the compensating controls are type/size/signature checks, parsing inside the worker with resource limits, and no execution or rendering of uploaded content. This is a recorded risk acceptance to revisit before opening sign-ups widely.

## 10. API conventions and contracts

- **Versioned prefix** `/v1`. Resource-oriented routes; thin handlers.
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
| `SUPABASE_SERVICE_ROLE_KEY` | api, worker | **Yes** | M6 | Storage admin and signed URLs |
| `NEXT_PUBLIC_SUPABASE_URL` | web | No | M1 | Auth client |
| `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` | web | No (public by design) | M1 | Auth client; the publishable key (`sb_publishable_…`) or a legacy anon key. Replaces the planned `…_ANON_KEY` name because Supabase is deprecating anon/service-role keys by the end of 2026 |
| `NEXT_PUBLIC_API_BASE_URL` | web | No | M1 | FastAPI base URL for the browser; compiled in at build time; required for production builds |
| `API_INTERNAL_BASE_URL` | web (server) | No | M1 | Address server-rendered pages use to reach the API (Docker: `http://api:8000`); defaults to the public URL |
| `LLM_PROVIDER` | api, worker | No | M3 | `gemini` · `openai` · `fake` (not allowed in staging/production) |
| `GEMINI_API_KEY` / `OPENAI_API_KEY` | api, worker | **Yes** | M3 | Provider credential |
| `LLM_MODEL_*` | api, worker | No | M3 | Model id per stage |
| `EMBEDDING_MODEL`, `EMBEDDING_DIMENSIONS` | worker | No | M6 | Fixed model and dimension (1536) |
| `BUDGET_*_PER_USER_PER_DAY` | api | No | M3 | Generation limits (A8) |
| `WORKER_CONCURRENCY`, `JOB_LEASE_SECONDS`, `JOB_MAX_ATTEMPTS` | worker | No | M3 | Queue behaviour |
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
| Malicious uploads | Size/type limits at the bucket and API, magic-byte validation, parsing in the worker with limits, no inline serving, private bucket + short-lived signed URLs |
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
| End-to-end | Playwright (`apps/web/e2e`, CI only) | Implemented for M1: sign up → goal → reload → sign out → sign in → **user B cannot see user A's data**. Extended each milestone toward roadmap → lesson → quiz → feedback → resume |
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
