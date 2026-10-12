# StudyPilot — Implementation Plan

| | |
|---|---|
| **Status** | Living plan — Milestone 1, the product part of Milestone 2 and the roadmap-generation part of Milestone 3 are implemented |
| **Date** | Written 2026-10-09 · last updated 2026-10-11 (roadmap generation) |
| **Related** | [PRD.md](PRD.md) · [ARCHITECTURE.md](ARCHITECTURE.md) |

**Done:** M1 (foundation, Supabase auth and database, protected goals API, sign-up/sign-in/dashboard), the product half of M2 (onboarding, goal management, settings; §4.5) and the roadmap slice of M3 (job queue, worker, `LLMProvider` + Gemini, planner, versioned roadmaps and UI; §4.6).
**Next action:** read a few real plans for quality, then — only when asked — **Milestone 4, lessons** (§5). Still open: the *deployment* half of M2 (Vercel, Render, a staging Supabase project; needs the owner's accounts) and the rest of M3 (OpenAI adapter, cost budgets).

---

## 1. How this plan works

- Work proceeds in **vertical slices**. Each milestone delivers a complete, tested, user-visible workflow; unfinished screens are not accumulated.
- Loop for every slice: **plan → implement → run tests → inspect the diff → fix → commit**.
- A feature is *done* only when all of these hold: the workflow works end to end · data persists · permissions are enforced · inputs and outputs are validated · loading/empty/error states exist · tests are written **and were run with output observed** · nothing regressed · documentation matches the implementation.
- No fake AI-generated learning data is used to make the product look finished. If a provider is unavailable, a clean adapter and a clearly labelled test double are used instead.

## 2. Repository and environment findings

### 2.1 Repository

| Item | Finding |
|---|---|
| GitHub repository | `Rishicreates20/StudyPilot` — **public, empty**, default branch `main` (checked through the GitHub API and `git ls-remote`) |
| Local checkout | None. The session started in an empty, temporary folder that is not a Git repository. This is a **greenfield** start. |
| Existing code, packages, migrations, CI | None |
| Specification | The 40-page source brief PDF (read in full). It is not committed. |

Because the repository is public, nothing secret may ever be committed. `.env*` files are git-ignored and `.env.example` will contain placeholders only.

### 2.2 Machine and runtimes (verified 2026-10-09)

| Capability | Status | Detail |
|---|---|---|
| Git | ✅ 2.55.0 | Identity unset; default branch `master`; `autocrlf=true` (handled by `.gitattributes`) |
| Node / npm | ✅ 24.21.0 / 11.19.0 | `pnpm` not installed → npm workspaces |
| `uv` | ✅ 0.12.15 | Python 3.14.7 and 3.12.14 installed under `uv` |
| Python on `PATH` | ❌ | Only the Microsoft Store shortcut exists; use `uv` |
| Python 3.14 stack | ✅ | `ssl`, HTTPS, `pydantic-core`, `cryptography`, `orjson`, `psycopg[binary]`, `asyncpg`, FastAPI, uvicorn all work |
| Python 3.12 stack | ❌ | `import ssl` and `psycopg` binary blocked by Smart App Control |
| Supabase CLI | ✅ via npm (2.120.0) | |
| Docker / WSL / `psql` / `gh` | ❌ | Local Supabase stack cannot run here |
| Smart App Control | ⚠️ On | Unsigned native code without reputation is blocked; test new native dependencies early |
| Windows long paths | ⚠️ Disabled | Use a short checkout path such as `C:\dev\StudyPilot` |

Implications are worked through in [ARCHITECTURE.md §15](ARCHITECTURE.md#15-development-environment).

### 2.3 What is missing

Everything application-level: monorepo, API, web app, migrations, CI, containers, tests. The credentials and accounts needed are listed in §6.

## 3. Milestone overview

| M | Name | Delivers | Needs from the account owner | Gate |
|---|---|---|---|---|
| **M1** | Foundation + Goals slice | Monorepo, health endpoints, CI, migrations + RLS tests, Supabase Auth, goal create/list/view, dashboard | Supabase dev project | — |
| **M2** | Goal management, onboarding, first deploy | Edit/pause/complete/archive, profile settings, onboarding wizard, responsive app shell ✅ · **walking-skeleton deployment** ⬜ | Vercel, Render, Supabase staging | — |
| **M3** | Job queue, AI foundation, roadmaps | Durable queue + worker ✅, `LLMProvider` + Gemini ✅, planner ✅ (intent parsing is folded into the planner's input), programmatic plan validation ✅, usage ledger ✅ and a daily count limit ✅ (cost budgets ⬜), job-progress UI ✅, roadmap overview ✅ · OpenAI adapter ⬜ | LLM API key (provider confirmed: Gemini) | — |
| **M4** | Lessons and study workspace | Structured lessons per item ✅, workspace UI ✅, simple-explanation toggle ✅, new versions (simpler, more examples, deeper) ✅, progress ✅, resume ✅ · next-topic prefetch ⬜ | — (reuses the M3 LLM key) | — |
| **M5** | Quizzes, mastery, next action | Question generation ✅, server-side grading ✅, answer-key isolation ✅, mastery ✅, weak-topic flags ✅, next-action ✅ (product slice done: §4.8; left over: reviewing real quiz quality, spaced revision, flashcards from wrong answers in M7) | — | **Private alpha** |
| **M6** | Documents, RAG, citations | Private upload, extraction + OCR, chunk/embed/index, hybrid retrieval, validated citations | — | **Beta-capable** (with M9) |
| **M7** | Learning loop | Flashcards (SM-2), YouTube curator, adaptive roadmap, reminders + streaks, analytics, content reports | YouTube Data API key | — |
| **M8** | Exports and polish | PDF then PPTX export, multilingual polish, light gamification | — | — |
| **M9** | Release hardening and beta | Security review, load/E2E suites, data deletion + export, monitoring, SMTP, privacy docs, pilot; Expo kickoff decision | Sentry (optional), SMTP, domain | **Beta** |

Sizing is relative, not a calendar promise: M1 is the largest "setup" milestone; M3 and M6 carry the most technical risk.

## 4. Milestone 1 — Foundation + Goals vertical slice

**Outcome:** an authenticated user creates a learning goal; it is stored in PostgreSQL under their ownership, protected by RLS, and shown on their dashboard after a reload; another user cannot see it. Everything is reproducible from the documented commands and verified in CI.

### 4.1 Preconditions (from the account owner)

1. **A Supabase development project** — provides project URL, publishable key, JWT verification details (JWKS URL or legacy secret), a pooler connection string and the project ref. These go into local, git-ignored `.env` files only. They must never be pasted into chat or committed.
2. **A short checkout path** (for example `C:\dev\StudyPilot`) for the implementation session, so `node_modules` stays under the 260-character path limit.
3. *(Optional but valuable)* Docker/WSL or a GitHub Codespace for running the full local stack. Without it, database-dependent checks run in CI.

### 4.2 Scope

**In:** monorepo scaffold · environment validation · health endpoints · structured logging + request IDs · RFC 9457 errors · JWT verification · RLS-scoped DB session · `profiles` and `learning_goals` with migrations, RLS and database tests · `GET /v1/me`, `POST/GET /v1/goals`, `GET /v1/goals/{id}` · generated API contract + drift check · sign-up/sign-in/sign-out · protected app layout · dashboard with real data · create-goal form · unit, integration, component and E2E tests · CI · Dockerfile + compose for the API · `.env.example` files · real README quickstart.

**Out (later milestones):** editing/archiving goals (M2) · onboarding wizard and settings UI (M2) · any AI call, queue or worker (M3) · documents (M6) · deployment (M2).

### 4.3 Ordered tasks

**M1a — Foundation** *(commit boundary 1)* — **implemented; see status notes**

- [x] Repository scaffold: root `package.json` (npm workspaces + cross-platform scripts), `.editorconfig`, Prettier config, `.nvmrc` = 24, `.python-version` = 3.14.
- [x] `services/api`: `uv` project, ruff + pyright (strict) config, app factory (`--factory`), **fail-fast settings validation** (exit code 78, names variables, never echoes values), structlog logging, request-ID middleware, problem+json error handlers, CORS allow-list, `/healthz` and `/readyz` (pluggable readiness registry; the database check is added in M1b).
- [x] `apps/web`: Next.js 16 App Router (Cache Components), strict TypeScript 6.0.3, Tailwind CSS 4, shadcn/ui (Radix, "nova" style, adapted to our tokens), design tokens with light/dark and automated WCAG contrast tests, Latin + Devanagari + Odia fonts, component library, Vitest + Testing Library, honest landing page, `/status`, `/design`, `/api/health`, fail-fast env validation.
- [x] `services/api/Dockerfile`, `apps/web/Dockerfile`, `docker-compose.yml`, `.dockerignore`, `.env.example` files (root, api, web).
- [x] GitHub Actions CI: API job, web job, Docker build-and-boot job, secret scan.
- [x] README, `docs/DEVELOPMENT.md`, `docs/DESIGN_SYSTEM.md` and `CLAUDE.md` updated with commands that were actually run.
- [ ] *Deferred to M1b:* `supabase/` (`supabase init`, `config.toml`) — it belongs with the first migration. *Deferred, optional:* `.devcontainer/`.

*Status notes (what is and is not verified):* `npm run check` passes locally (formatting, lint, types and tests for web and API). Both apps were started and their health endpoints and pages exercised in a browser. **Not verified locally:** Docker builds and Compose (no Docker on the dev machine) and the GitHub Actions workflow (YAML parses, but it has not run). Both are exercised by CI on the first push.

*Exit check:* one command runs lint + type-check + unit tests for both apps and passes ✅; both health endpoints respond ✅; no secret is tracked ✅; CI green on `main` ✅ (run 38053557495, commit 301c86e: secret scan, API, web, Supabase stack and Docker jobs all passed).

**M1b — Data and API slice** *(commit boundary 2)* — **implemented; see status notes**

- [x] **Time-boxed spikes** (outcomes in the ARCHITECTURE decision log):
  - **S1** — role switching and claims inside a request transaction: verified on PostgreSQL 16 through psycopg 3 and a pool (ADR-006, ADR-021). Under Supabase's own roles: ✅ the CI job `supabase-stack` passed (run 38053557495).
  - **S2** — JWT verification: both modes implemented with per-mode algorithm allow-lists and tested with real signatures; Supabase's docs checked on 2026-10-10. Which algorithm the local stack issues is detected in CI, not assumed. Genuine Supabase tokens: ✅ the same CI run.
  - **S3** — Next.js 16 uses `proxy.ts`; `@supabase/ssr` sessions are refreshed there with `getClaims()`. Verified by unit tests, and the real refresh by the Playwright journey in that CI run ✅.
  - **S4** — toolchain pinned in M1a (TypeScript 6.0.3, Next 16.4, `typescript-eslint` 8.71).
- [x] Migrations `20261009130000_profiles.sql` (extensions-free; `set_updated_at()`, `profiles`, `handle_new_user` trigger with backfill, RLS, explicit grants) and `20261009130100_learning_goals.sql` (check constraints, index, RLS, column-level grants, per-user ownership key).
- [x] Database tests (pytest on a real PostgreSQL 16 instead of pgTAP, ADR-022): owner can read and write only their own rows; another user cannot; `anon` has no access; constraints reject invalid rows; profile created on sign-up; guards that fail the build if a `public` table lacks RLS.
- [x] API: Pydantic schemas, psycopg repositories, services, routers (`/v1/me`, `/v1/goals`), `user_transaction`, cursor pagination, 404 on non-owned resources, per-user goal cap.
- [x] Tests: settings validation; JWT (valid, missing, malformed, expired, wrong audience/issuer/algorithm, bad signature, anonymous, non-UUID subject); JWKS cache behaviour; authorization (user B gets 404 on user A's goal); validation errors; pool isolation; failure handling. **250 pass, 1 skipped** (the genuine-stack module). No schema drift test: there are no ORM models (ADR-021).
- [x] OpenAPI export → `packages/contracts` (generated types) → `npm run contracts:check`; regeneration is deterministic. The CI step passed in run 38053557495 ✅.

**M1c — Web slice** *(commit boundary 3)* — **implemented; see status notes**

- [x] Sign-up, sign-in, sign-out; HttpOnly cookie sessions refreshed in `proxy.ts`; protected `(app)` layout that re-checks the session; uniform "email or password is incorrect" message; "check your email" state when confirmation is on; a confirm route that refuses open redirects and unknown link types.
- [x] Dashboard: goals from the API with skeleton, empty state, and error state with retry; session-ended handling that cannot loop (ADR-024).
- [x] Create-goal form (native form + Server Action + Zod, not React Hook Form) showing server-side field errors; success returns to the dashboard with the new goal visible.
- [x] Vitest tests (283): redirect safety, schemas, messages, auth and goal Server Actions with only Supabase and the API mocked, the typed API client, the proxy and cookie hardening, the confirm route.
- [x] Playwright journey (`apps/web/e2e`): sign up → create goal → reload → HttpOnly cookie check → sign out → blocked → sign in → **second user sees nothing**. Passed against a genuine Supabase stack in CI run 38053557495 ✅. (Superseded by the longer journey in §4.5.)

**M1d — Review and documentation** *(commit boundary 4)*

- [x] Security pass. Ownership paths, grants and error bodies are covered by tests. **Bundle search (2026-10-10):** the web app was built with canary values for `DATABASE_URL`, the JWT secret, a service-role key and a secret key in its environment; none appears anywhere in the 422 files of `.next`, there are no JWT-shaped strings, and the browser bundle contains no Supabase client code and not even the publishable key (auth runs on the server). The only `sb_secret_` matches are the Supabase library's own key-prefix checks. Not done: a dependency-level review beyond `npm audit`.
- [x] Accessibility pass (keyboard, focus, contrast) and a mobile-width pass on the new pages — done for every signed-in page in M2 (§4.5).
- [x] README, ARCHITECTURE (ADR-021…024, S1–S3 outcomes, ADR-006 status), `.env.example` files, `docs/SUPABASE_SETUP.md` and the configuration reference updated to match what exists.

*Status notes (what is and is not verified):* Run locally and observed: web typecheck, lint, formatting and 283 Vitest tests; production web build; API 250 pytest tests against a real PostgreSQL 16 and strict pyright with 0 errors; contract regeneration is byte-identical. Not runnable locally (no Docker, no Supabase project connected): genuine Supabase Auth, Supabase's real roles and `auth` schema, the Docker images. **Observed in CI** (run 38053557495 on commit 301c86e): all five jobs green — secret scan, API, web, the `supabase-stack` job (genuine tokens, real roles, the Playwright journey) and Docker.

### 4.4 Acceptance criteria

| # | Criterion | Evidence | Status |
|---|---|---|---|
| 1 | A new user can sign up and sign in; an unauthenticated call to a protected route returns **401** | 401 matrix in API tests; real sign-up/sign-in in the stack job and Playwright | 401 ✅ · sign-up/sign-in ✅ CI (run 38053557495) |
| 2 | Creating a goal persists a row with `user_id` = the caller | API and database tests on real PostgreSQL | ✅ |
| 3 | The goal appears on the dashboard and survives a reload | Playwright | ✅ CI (run 38053557495) |
| 4 | User B gets **404** for user A's goal; a database session acting as B cannot select A's rows | API and database tests; the same under Supabase's roles in the stack job | Real PostgreSQL ✅ · Supabase roles ✅ CI |
| 5 | `anon` has no table access to application tables | Guard tests; stack job | ✅ locally · stack ✅ CI |
| 6 | Invalid input produces field-level errors in the UI and a problem+json 422 | Web action and schema tests; API validation tests | ✅ |
| 7 | The dashboard shows skeleton, empty and error-with-retry states | Implemented; empty and populated states exercised by the Playwright journey; the feedback, load-error and goal components have unit tests; the dashboard page itself has no unit test | ✅ (page covered by the browser journey) |
| 8 | Missing or invalid environment variables stop the API at startup without echoing secrets | Settings tests | ✅ |
| 9 | `/healthz` and `/readyz` behave correctly (readiness fails when the database is unreachable) | Health and failure tests | ✅ |
| 10 | The generated API client is in sync with the OpenAPI document (CI-enforced) | Deterministic regeneration observed locally; CI step passed | ✅ locally · ✅ CI (no drift test: no ORM models) |
| 11 | Lint, type-check, unit, integration and E2E suites pass **in CI**, outputs read | CI run 38053557495 | ✅ for commit 301c86e; and for 063fc69 (the M2 slice), CI run 38109598536: all five jobs passed |
| 12 | A new contributor can follow the README to a running app | `docs/SUPABASE_SETUP.md` written from Supabase's current docs | ⏳ not yet followed by someone fresh |

### 4.5 Milestone 2, product half — onboarding, goal management, settings

**Outcome:** a new user signs up, answers three optional onboarding steps, creates a goal, sees it on the dashboard, edits it, pauses/completes/archives it, and finds every change after a refresh. Nobody can read, change or delete another user's goal.

- [x] **Migration `20261010100000_goal_lifecycle_and_preferences.sql`:** `learning_goals` gains `learning_preferences`, `completed_at` and `archived_at`; a trigger allows only legal status moves (active ⇄ paused, active/paused → completed, completed → active, any open or completed → archived, archived → active) and makes archived goals read-only; the timestamps are set by the database and checked against the status; clients get `UPDATE` only on the editable columns and may `DELETE` only archived rows. `profiles` gains `default_daily_minutes`, `preferred_languages`, `learning_preferences` and `onboarding_completed_at` (backfilled for accounts that already have goals).
- [x] **API:** `PATCH /v1/goals/{id}` (only the fields sent; `null` clears the description or target date), `PUT /v1/goals/{id}/status`, `DELETE /v1/goals/{id}` (archived only), `GET /v1/goals?status=…`, `GET /v1/goals/summary`, `PATCH /v1/me`, `POST /v1/me/onboarding/complete`. Goals created without minutes, languages or preferences take the user's saved defaults. Stable error codes: `GOAL_ARCHIVED`, `INVALID_STATUS_TRANSITION`, `GOAL_NOT_ARCHIVED`, `GOAL_LIMIT_REACHED` (restoring respects the cap). The target date must be today or later (one day of grace for time zones) and within 5 years, and is checked only when it changes, so a goal whose date later passes can still be edited.
- [x] **Web:** onboarding wizard (`/onboarding`, three steps, every step skippable), dashboard with real counts and separate *In progress* / *Completed* lists with their own "load more" cursors, goal page, edit page, archived goals, settings, destructive-action confirmation dialogs (archive, delete), success/failure notices, `not-found` page, a phone-width navigation menu.
- [x] **Tests (run locally, output observed):** 439 API tests passed, 1 skipped (the genuine-stack module, which needs Docker); 537 web unit/component tests passed; 16-test Playwright journey passed. Highlights: every transition in a table (legal and illegal) at the database and the API; archived read-only; delete only when archived; invalid input for every field; no token, bad token, another user's goal (read, edit, status, delete → 404, untouched); defaults applied; the web actions with only Supabase and the API mocked.
- [x] **Accessibility and responsive pass:** axe-core (WCAG 2.0/2.1/2.2 A and AA plus best-practice rules) over sign-up, the three onboarding steps, dashboard, goal page, archive dialog, edit, new, settings and archived pages, light and dark, 1280 px and 375 px wide: **0 violations**. Phone layout checked for horizontal overflow.
- [ ] **Deployment half of M2** (Vercel, Render, a staging Supabase project, migration-deploy job): **not started**; it needs accounts only the owner can create (§6).

*Status notes (what is and is not verified):* Everything above marked with test counts ran on the primary machine against a real PostgreSQL 16. The **Playwright journey ran locally against a stand-in for Supabase Auth** (a small GoTrue-compatible server used only on this machine, not committed) because Docker is unavailable; it exercises the real web app, the real API and the real migrations, but not Supabase's own Auth service or roles. The same journey, the extended `tests/supabase_stack` module and the migration under Supabase's real roles ran in the CI `supabase-stack` job for the M2 commit (063fc69, run 38109598536): **all five jobs passed** ✅. When the migration is applied to a hosted project (`npx supabase db push`), no new environment variable is needed.

*Deliberate choices:* the `general` goal type from M1 is kept beside the five listed in the brief (a learner who "just wants to get better at something" is not forced into a wrong category); preferences live on `profiles`, not in a new table (ADR-025); the browser never redirects from a prefetched, data-dependent page (ADR-026).

### 4.6 Milestone 3 — job queue, AI foundation and roadmap generation

**Outcome:** from a goal, the learner asks for a roadmap; a background job produces a structured plan, the server validates it against their real constraints, and it is stored as a versioned roadmap that survives refreshes and can be revised without losing earlier versions. No lesson, quiz or document feature is involved.

- [x] **Migration `20261011100000_jobs_and_roadmaps.sql`:** `generation_jobs` (queue, lease, idempotency, one active job per goal, learner cancel), `ai_usage_events`, `roadmaps`, `roadmap_modules`, `roadmap_items`, `roadmap_item_prerequisites`, with row security, explicit grants, composite ownership keys and the version/exactly-once rules in the database (ADR-029).
- [x] **AI layer (`app/ai`):** `LLMProvider` with typed errors that say whether to retry; `GeminiProvider` over REST (ADR-027); `FakeProvider` (labelled sample, refused in staging/production); the planner prompt `roadmap-planner/v1` (learner text fenced as data); the Pydantic roadmap schema; programmatic validation of daily minutes, horizon, prerequisites and order, objective coverage, revision timing, language, keys, evidence and "unknowns for exam goals" (ADR-030); one bounded repair then `PLAN_INVALID`.
- [x] **Worker (`app/jobs`, `python -m app.worker`):** `SKIP LOCKED` claim, heartbeat lease, crash recovery, retries with exponential backoff and jitter, checkpoint of the validated plan, and one transaction that stores the roadmap and finishes the job (ADR-028). The privileged database session exists only here (guard test).
- [x] **API:** start (202, `Idempotency-Key`, daily allowance, readiness checks), versions, jobs, read a roadmap, make a version current, cancel and retry a job. 401 and 404 on every endpoint for the wrong caller.
- [x] **Web:** the goal page's roadmap section (empty, live progress, failure with retry, ready), the roadmap page (overview, assumptions and "check these yourself", objectives, modules and topics, revision, optional extras, day-by-day schedule, version history), revise/regenerate dialog, make-current, read-only for archived goals.
- [x] **Tests (run locally, output observed):** 860 API tests passed, 1 skipped (the genuine-stack module); 642 web tests passed; the 21-test Playwright journey passed (real API, real worker, real migrations, built-in test provider, stand-in for Supabase Auth). Highlights: structured-output validation; invalid, vague and time-starved goals; the daily budget at every size; persistence; retries and backoff; a crashed worker; version uniqueness; the same job claimed twice storing one roadmap; ownership for every route.
- [ ] **Not built:** OpenAI adapter; cost budgets in currency (a per-learner daily *count* exists); `LISTEN/NOTIFY`; uploaded-document evidence (the schema carries it but it is always empty until M6); a job history page.

*Status notes (what is and is not verified):*

| Claim | Status |
|---|---|
| The whole flow (create goal → generate → validated plan stored → shown → survives reload → revise → switch versions → archived read-only → another user gets 404) | ✅ observed locally in a real browser against the real API, worker and database, with the **built-in test provider** and a **stand-in for Supabase Auth** |
| Database rules, queue concurrency, recovery, retries, versions, ownership | ✅ observed locally against PostgreSQL 16 |
| The jobs and roadmaps migration and the new database, queue and API behaviour under Supabase's own roles | ✅ CI run 38115233920 (commit 287ba01): all five jobs passed, including `supabase-stack` with the four new roadmap tests |
| The browser journey (generate, revise, switch, archive, other user) against genuine Supabase Auth | ✅ CI run 38118004781 (commit ec911cf): all five jobs passed, with the real API, worker and migrations and the built-in test provider (locally the same journey also passed against the stand-in) |
| **A live Gemini call** | ✅ **observed on 2026-10-11** with the owner's key through the real planner (`scripts.llm_smoke`): a valid plan on the first attempt with `gemini-3.5-flash-lite` (6 s), `gemini-3.6-flash` (18 s) and `gemini-3.8-flash` (96 s). Two things were found only by calling the live API and fixed: the docs' `responseFormat` request shape is rejected (the adapter now sends `responseMimeType` + `responseJsonSchema`), and a schema containing `maxItems` gets a bare 400 (it is no longer sent). The default model is `gemini-3.6-flash`. |
| Quality of real plans (topic choice, pacing, language) | ⏳ a real plan validates against every rule, but a person has not yet read one for quality, and only English was tried |

*Deliberate choices:* the AI is called only by the worker, never inside a web request; the new version becomes current at once (history one click away) instead of waiting for approval; a learner's revision note is data inside the fence, not an instruction; revision sessions use the prerequisites table (they "need" the topics they revisit); optional enrichment has no day.

### 4.7 Milestone 4 — lessons and the study workspace

**Outcome:** the learner opens a roadmap topic, has a lesson written for it in the background, studies it in a readable workspace, asks for a simpler explanation or another version, and resumes later exactly where they left off. No quiz, document or video feature is involved.

- [x] **Migration `20261011180000_lessons.sql`:** `lessons` (typed `jsonb` document, versions, one current per topic, one per job, worker-only writes), `lesson_progress` (own sections only, completed means every section, read-only on archived goals), lesson jobs on `generation_jobs` (`item_id`, one active per topic, a trigger that only accepts topics of the current roadmap), row security and explicit grants. Applied to the hosted project through the Supabase tools on 2026-10-11 (version recorded as `20261011180000`).
- [x] **AI layer (`app/ai/lesson`):** the flat `DraftLesson` the model fills in and the strict `Lesson` that is stored (ADR-032); context from the roadmap (level, objectives, what came before and after, language); prompt `lesson-writer/v1` (inputs fenced as data, no links or citations, plain text only); code-side checks and one repair (ADR-033); the built-in sample lesson for the test provider.
- [x] **Worker:** the runner now dispatches by job type (`runtime.py`, `runner.py`, `roadmap_job.py`, `lesson_job.py`); a lesson job loads the topic, writes, validates, checkpoints and stores in one transaction with the job's completion; usage events record `lesson.write` / `lesson.repair`.
- [x] **API:** `POST /v1/roadmap-items/{id}/lessons` (202, `Idempotency-Key`, adjust / feedback / regenerate), `GET /v1/roadmap-items/{id}/study` (everything the page needs, one call), `PUT /v1/lessons/{id}/progress`; roadmap items and summaries now carry study state; cancel and retry work for lesson jobs; limits (per-topic, in-flight, daily).
- [x] **Web:** the study page (`/goals/[id]/learn/[itemId]`: empty, live progress, failure with retry, ready), the reader with sticky contents, mobile Contents sheet, per-section done toggles, finish, "Explain simply", "Write another version" dialog, version list, previous and next topic, resume banner; the roadmap shows each topic's study state and a Continue studying button; the goal page shows topics finished.
- [x] **Tests (run locally, output observed):** 1111 API tests passed, 1 skipped (the genuine-stack module); 779 web tests passed; the 28-test Playwright journey passed (real API, real worker, real migrations, built-in test provider, stand-in for Supabase Auth). Highlights: lesson validation (empty and thin sections, links, citations of material that was never supplied, language, length), repair and failure, regeneration versions, persistence, retry and backoff, a checkpoint that is not paid for twice, exactly-once storing, ownership on every route, progress rules in the database, rendering of every block type with hostile text, resume, saving and failure of saving, the read-only archived goal.
- [ ] **Not built:** prefetching the next topic's lesson; "make this version current" for lessons (an earlier version is readable but the newest stays the default); uploaded-document evidence (M6, so citations are always empty today); a separate "Explain like I'm five" level; keyboard shortcuts for the reader.

*Status notes (what is and is not verified):*

| Claim | Status |
|---|---|
| The whole flow (open a topic → write the lesson → study it → explain simply → progress → reload and resume → another version → previous and next topic) | ✅ observed locally in a real browser against the real API, worker and database, with the **built-in test provider** and a **stand-in for Supabase Auth**, on desktop and a phone-sized screen |
| Database rules for lessons, jobs and progress; limits; ownership | ✅ observed locally against PostgreSQL 16 |
| The lessons migration under Supabase's own roles | ✅ applied to the hosted StudyPilot project without error and the security advisor reported nothing new; the genuine-Supabase CI job passed on the next push: run 38157146086 (commit c485854), read 2026-10-12 |
| **A live Gemini lesson** | ✅ **observed on 2026-10-11** with the owner's key through the real writer (`scripts.llm_smoke lesson`): a valid lesson from `gemini-3.5-flash-lite` after one repair (an empty block). `gemini-3.6-flash` answered "high demand" (503) on every attempt that day, so the default model's lesson quality is **not** yet observed. One live answer was rejected by a too-strict 100-character limit on a callout title: found only by calling the live API, fixed by trimming cosmetic text. One run of `flash-lite` stopped at the output limit (retryable, handled by the queue) |
| Quality of real lessons (accuracy, pacing, tone) | ⏳ one lesson about Rust ownership was read and was accurate with correct code, but a person has not reviewed lessons across subjects or in Hindi or Odia |

*Deliberate choices:* the simple explanation is written with the lesson (instant and free to show) and a rewrite is a new version built from the existing lesson, so it cannot drift to another topic; progress is per version and written with the learner's own identity so the database can refuse impossible states; the reading position is measured from scroll geometry rather than visibility events so a jump to the end still counts; nothing in a lesson's text can become HTML or a link.

### 4.8 Milestone 5 — quizzes, results and skill-gap detection

**Outcome:** from a topic's lesson the learner takes a short quiz, submits it, sees the right answers and why, sees how well they know the topic and which parts are weak, and is told one relevant next step. The correct answers never reach the browser before submission.

- [x] **Migration `20261012100000_quizzes.sql`:** `quizzes`, `questions`, `question_answer_keys` (row security on, **no policy, no grant**), `quiz_attempts` (`unique (quiz_id)`), `quiz_answers` (copy of the feedback, `pending` ⇔ no points, points never above the worth), `topic_mastery` (a rebuildable cache); clients can only read their own; quiz and grading jobs on `generation_jobs` (`attempt_id`, one active job per topic and kind and per attempt, a trigger requiring a current lesson). Database tests cover every grant, the key table, the uniqueness rules, composite ownership keys and malformed rows (one test found a NULL-options hole in a check, now closed).
- [x] **AI layer (`app/ai/quiz`, `app/ai/grading`):** the flat `DraftQuiz` the model fills in and the strict stored quiz (ADR-036); the context from the topic, its objectives and the lesson; prompts `quiz-writer/v1` and `short-answer-grader/v1` (learner text fenced as data); `build_quiz` / `validate_quiz` (one correct option, option quality, duplicate and repeat detection, objective mapping and coverage, answer leaks, explanation contradicting the key, language, kind and difficulty mix, no links) with one repair; the marker whose reply is checked and whose points are summed by code (ADR-037).
- [x] **Grading and mastery (`app/grading`, `app/learning`):** submission checks, deterministic grading, answer feedback copied at submission, idempotent repeats, learner review, retry of failed marking, a rebuildable mastery cache; `compute_mastery` and `recommend` are pure functions with no database or model.
- [x] **Worker:** `quiz` and `grade` job types with stages, checkpoints (a validated quiz or marking is not paid for twice), cancel, lease checks and one-transaction storing; usage events record `quiz.write` / `quiz.repair` / `grade.short_answer` / `grade.repair`.
- [x] **API:** `POST /v1/roadmap-items/{id}/quizzes` (202), `GET …/quizzes`, `GET …/assessment`, `GET /v1/quizzes/{id}` (questions and options only), `POST /v1/quizzes/{id}/attempts` (201, or 200 for a repeat with the same `Idempotency-Key`), `GET /v1/quiz-attempts/{id}`, `POST …/regrade`, `PUT /v1/quiz-answers/{id}/review`, `GET /v1/goals/{id}/progress`; retry works for quiz jobs.
- [x] **Web:** the quiz card on the study page (start, live progress, ready, failed with retry, last result and mastery), the quiz page (a native form; a live "x of y answered"), the results page (score, estimate labels, rubric, model answer, per-question explanations, review form, marking progress and failure, mastery by objective, the recommendation), "Your mastery" on the goal page, "Where you stand" on the dashboard.
- [x] **Tests (run locally, output observed):** see the status table. Highlights: question validation (49) and writer/marker (the repair and failure paths), mastery and recommendation as pure functions, database rules, secure answer handling (nothing readable before submission, invalid/duplicate/foreign ids refused, another learner's quiz is 404 and nothing is stored), repeated submissions, idempotency, the grading job's failure paths, learner review winning over a waiting job, mastery across attempts, and an architecture test that only `services/quizzes.py` may call the grader and request code cannot name the key table.
- [ ] **Not built:** a person's review of real quiz quality; question reports (M7); spaced revision and flashcards from wrong answers (M7); a retake of the same questions (deliberately not offered, ADR-038); partial credit for multiple-select questions (none exist); exporting results (M8).

*Status notes (what is and is not verified):*

| Claim | Status |
|---|---|
| The whole flow (a quiz is written from the lesson → taken → submitted → results with explanations → weak topic and a practice quiz → a better score that does not erase the weak one → "getting there" → the next step moves on; a learner's review of an AI-estimated short answer; mastery on the topic, goal and dashboard pages) | ✅ observed locally in a real browser against the real API, worker and database: **37 Playwright scenarios passed** (9 new), with the **built-in test provider** and a **stand-in for Supabase Auth** |
| Answers never leave the server early; invalid, foreign and duplicate submissions are refused; repeats are idempotent; another learner gets 404 everywhere | ✅ 1498 API tests passed, 1 skipped (the genuine-stack module); pyright (strict) and ruff clean; 893 web tests passed; `tsc` and ESLint clean |
| Database rules (grants, the key table, one attempt per quiz, ownership keys, malformed rows) | ✅ observed locally against PostgreSQL 16; one test found that a question with `null` options slipped past a check (fixed in the migration before it was applied anywhere) |
| The quizzes migration under Supabase's own roles | ✅ applied to the hosted StudyPilot project without error (version row renamed to `20261012100000`); `question_answer_keys` has **no** grant for `anon` or `authenticated` there (queried), the other assessment tables are `select`-only; the security advisor's only new item is the intended INFO "RLS enabled, no policy" on `question_answer_keys`. The genuine-Supabase CI job first **failed** on the M5 commit 169cd91 (run 38150473463, the genuine-stack API test step), was fixed in c485854, and **passed with all five jobs** in run 38157146086 (read 2026-10-12), including the two new quiz tests and the browser journey (those tests are not run locally) |
| Accessibility of the new pages (axe-core, WCAG 2.2 AA, light and dark, phone and desktop) | ✅ 0 violations after one fix (a skipped heading level) |
| **A live Gemini quiz and marking** | ✅ **observed on 2026-10-11** (`scripts.llm_smoke quiz`, `gemini-3.5-flash-lite`): a valid 5-question quiz on the first try, and a first-try marking of a short answer against its rubric. It used the built-in *sample* lesson, so the questions were about that sample. A live *lesson* on that model was blocked or truncated on two tries the same day, and the default `gemini-3.6-flash` still answered 503 |
| Quality of real quizzes and of real short-answer marking (are the questions fair? does the marker agree with a person?) | ⏳ not judged by a person |
| CI for the commit that contains this slice | ⏳ read once after the push |

*Deliberate choices:* the correct answer and explanation are copied into the learner's answer row when they submit, so a result never reads the key table and nothing is revealed earlier; mastery and the recommendation are pure functions over stored answers, and the band is derived from today's thresholds when it is shown; a quiz is taken once and practice means new questions aimed at the weakest objectives (chosen by the server); the model never adds up a score; the learner's review of a short answer always wins; a topic mastered in a quiz is not sent back to "start" its lesson.

## 5. Later milestones in outline

Each gets its own detailed breakdown, written at the end of the previous milestone using what was learned.

**M2 — remaining: first deploy.** Theme and Indic-font verification on real devices · **deploy the skeleton** to Vercel + Render + a staging Supabase project · CI migration-deploy job (staging automatic, production manual) · confirm pooler mode and IPv4/IPv6 behaviour on Render. *(Goal management, profile settings, the onboarding wizard and the responsive shell are done: §4.5.)*

**M3 — Job queue, AI foundation, roadmap generation.** *(Roadmap slice done: §4.6. Left over: OpenAI adapter, cost budgets, uploaded-document evidence from M6.)* Migrations + pgTAP for `generation_jobs`, `ai_usage_events`, `roadmaps`, `roadmap_items`, `roadmap_item_prerequisites` · queue claim/lease/heartbeat/retry/cancel · worker process and compose service · `LLMProvider`, first real adapter, `FakeProvider` for tests · versioned prompts for intent parser and planner · **programmatic** plan validators (time budget, acyclic ordered prerequisites, objective coverage, unique sequence) with one bounded repair attempt · budgets and usage ledger · `Idempotency-Key` · job status API and progress UI · roadmap overview with learner edits · evaluation fixtures (malformed output, infeasible plans) · worker-kill and duplicate-submission tests. *Verify current provider SDK APIs and model names first.*

**M4 — Lessons and study workspace.** *Slice done: §4.7. Left over: prefetch of the next topic, uploaded-document evidence (M6), a separate "Explain like I'm five" level.* `learning_materials` · lesson schema and validator · per-item lesson job (on demand, with prefetch of the next item) · lesson renderer for structured JSON (headings, code, callouts, glossary) · simple-explanation toggle from stored content · item progress and resume position · mobile-first workspace · general-knowledge labelling when no sources exist.

**M5 — Quizzes, mastery, next action (private alpha gate).** *Slice done: §4.8. Left over: a person's review of real (non-sample) quiz quality, evaluation fixtures for question quality, "report this question" (M7), spaced revision.* Migrations + pgTAP for quizzes, questions, `question_answer_keys`, attempts, answers, `topic_mastery` · assessment generator and validators (one correct option, duplicate detection, objective mapping) · submit/grade endpoint with server-side scoring · results with explanations after submission only · deterministic mastery and weak-topic thresholds · next-action recommendation with reason · progress page · tests asserting no key/explanation leaks before submission.

**M6 — Documents, RAG, citations (beta-capable gate).** Private bucket + storage policies · upload → complete → worker validation (size, magic bytes, ownership) · `pypdf` extraction, vision OCR behind `TextExtractor`, reviewable text · page-aware chunking · embeddings (fixed 1536 dims, model recorded) · HNSW + full-text hybrid retrieval scoped to the user in SQL · citation validator · "insufficient evidence" behaviour · prompt-injection fixtures · document-grounded roadmaps and lessons. *Syllabus-by-URL fetching needs SSRF protection (allow-listed schemes/hosts, no internal addresses, size/time limits) and is deferred until that is built.*

**M7 — Learning loop.** Flashcards with SM-2-style scheduling and review UI · YouTube curator (verify real quota first; cache; language filters; `last_verified_at`) · adaptive roadmap trigger from mastery · in-app reminders and streaks · learner analytics · `content_reports` and a report-a-problem control.

**M8 — Exports and polish.** PDF export first (verify Devanagari/Odia font embedding and page breaks), then PPTX · export jobs in the queue · private bucket + signed download URLs · multilingual refinements · light, supportive gamification.

**M9 — Release hardening and beta.** Full security and RLS audit · load tests · complete E2E suite · account deletion including storage objects · data export · retention settings · Sentry and dashboards · custom SMTP for auth email · privacy policy and terms (including disclosure of AI-provider processing) · backup/restore drill · runbooks · small-user pilot with a feedback loop · decision on starting the Expo app.

## 6. External services, accounts and credentials

Nothing below is assumed to exist. Provide secrets only through local `.env` files, Vercel/Render environment settings or GitHub Actions secrets — never in chat or Git.

| Service | Needed by | What is required | Notes |
|---|---|---|---|
| **Supabase** (dev) | M1 | Project URL · anon key · JWKS URL or JWT secret · pooler connection string · project ref | Choose the region (A12). Staging and production projects later. |
| **GitHub** | M1 | Repository (exists) · Actions enabled | `SUPABASE_ACCESS_TOKEN` and related secrets only when CI needs a hosted project (M2). Public repo ⇒ secret scanning is on by default. |
| **Vercel** | M2 | Account linked to the GitHub repo; root directory `apps/web` | |
| **Render** | M2 | Account; web service + background worker | Paid tier needed for an always-on worker. |
| **LLM provider** | M3 | `GEMINI_API_KEY` or `OPENAI_API_KEY`; confirm provider (A4); spending cap set in the provider console | Free tiers have quotas that affect tests and demos. |
| **Embedding model** | M6 | Same provider key; model with 1536-dim output | |
| **YouTube Data API** | M7 | Google Cloud project + API key; **verify the assigned quota** | |
| **SMTP provider** | M9 | Credentials for Supabase Auth custom SMTP | Default Auth email is rate-limited. |
| **Sentry** (optional) | M9 | DSNs for web and API | |
| **Docker / Codespaces** (optional) | M1 | Local Linux containers | See ARCHITECTURE §15.3. |
| **Domain** | M9 | Custom domain for web/API | |

## 7. Risk register (highest first)

| # | Risk | Likelihood | Impact | Mitigation | When |
|---|---|---|---|---|---|
| **1** | **Cannot run the Supabase stack locally** (no Docker/WSL; Smart App Control may block installs). RLS, migrations and integration tests could go unverified. | High | High | CI is the gate; hosted dev project for opt-in integration tests; Codespaces/dev container; never declare DB work done without observed CI output. | M1 |
| **2** | **Answer keys or other private data exposed** through a policy mistake (the source schema co-locates keys with questions; RLS is row-level). | Medium | High | `question_answer_keys` isolation, composite ownership FKs, RLS-scoped sessions, Data API unexposed, pgTAP + response-shape tests. | M1, M5 |
| **3** | **AI cost or quality failure** — runaway regeneration, hallucinated citations, infeasible plans. | High | High | Budgets and usage ledger land with the first AI feature; plan feasibility, citations and answer keys validated by code; bounded repairs; checkpointed retries. | M3–M6 |
| **4** | **Platform behaviour differs from assumptions** (Supabase JWT signing, Data API grants, pooler modes, Next.js 16 request interceptor, AI SDK major versions). | Medium | Medium | Marked **[verify]**; spikes S1–S4; read official docs before each integration. | M1, M3 |
| **5** | **Toolchain incompatibility** — TypeScript 7 is "latest" but `typescript-eslint` requires TypeScript < 6.1; Python 3.14 wheel gaps for future libraries. | High | Medium | Pin TypeScript 6.0.x; verify each native dependency under Smart App Control before adopting; fall back to 3.13 only with evidence. | M1 |
| **6** | **Schema/contract drift** between SQL migrations, API schemas and TypeScript types. | Medium | Medium | No ORM models to drift (ADR-021); OpenAPI regeneration check in CI. | M1 |
| **7** | **Scope creep** toward "all subjects and exams" and cosmetic features. | High | Medium | Persona A, P0 gate at M5, postponed-features list, milestone exit criteria. | Ongoing |
| **8** | **Windows environment friction** — 260-character paths, reputation-based blocking of new native binaries. | Medium | Low–Medium | Short checkout path; lockfiles; test new natives early; CI/Codespaces fallback. | M1 |
| **9** | **Public repository** exposes docs and any accidental secret. | Low | High | Placeholders only; `.gitignore`; secret scanning in CI; decide public/private (Q4). | Ongoing |
| **10** | **Prompt injection / malicious files** once documents arrive. | Medium | High | Model has no tools; delimited data; validation of IDs; magic-byte checks; limits; SSRF defences. | M6 |
| **11** | **Student privacy / minors.** | Low now | High later | Adult launch segment; review before Persona C. | Before B/C |

## 8. Version snapshot (registry "latest" on 2026-10-09)

Pins are decided at the start of M1 after checking compatibility; this table records the starting point, not a commitment.

| Package | Latest | Plan |
|---|---|---|
| Next.js | 16.4.0 | Adopt; confirm with S3 |
| React | 19.3.0 | Adopt |
| **TypeScript** | **7.0.2** | **Pin 6.0.3** (`typescript-eslint` 8.71.1 requires `<6.1.0`) |
| Tailwind CSS | 4.3.3 | Adopt |
| `@supabase/supabase-js` / `@supabase/ssr` | 2.117.3 / 0.12.7 | Adopt; confirm API in S3 |
| Zod / React Hook Form | 4.6.5 / 7.89.0 | Adopt |
| Vitest / Playwright | 5.0.3 / 1.64.0 | Adopt |
| `openapi-typescript` | 7.13.0 | Adopt (plus `openapi-fetch`) |
| FastAPI / uvicorn | 0.143.0 / 0.54.0 | Adopt |
| Pydantic / pydantic-settings | 2.14.0 / 2.15.0 | Adopt |
| SQLAlchemy | 2.1.4 | Adopt (async, psycopg 3) |
| psycopg | 3.3.6 | Adopt (binary works on Python 3.14 here) |
| structlog / httpx / pytest / ruff | 26.1.0 / 0.28.1 / 9.1.1 / 0.16.10 | Adopt |
| pgvector (Python) | 0.5.1 | Adopt in M6 |
| pypdf | 6.19.0 | Adopt in M6 |
| `openai` / `google-genai` | 3.26.1 / 2.29.0 | **Read current docs before use (M3)** |
| Supabase CLI | 2.120.0 | Dev dependency |
| Alembic | 1.20.0 | **Not used** (ADR-002) |

Installed locally: Node 24.21.0, npm 11.19.0, Python 3.14.7 (via `uv` 0.12.15), Git 2.55.0.

## 9. Working agreement

- **Branches and commits.** Short-lived branches (`feat/m1-…`), Conventional Commits, pull requests even when working solo so CI runs before merge. Protect `main` once CI exists.
- **Evidence before claims.** A test, build or deployment is reported as passing only after its output was observed. Unverified work is described as unverified.
- **Docs travel with code.** Behaviour changes update README, ARCHITECTURE and `.env.example` in the same change.
- **Decisions are recorded.** New or changed technical decisions go into the ARCHITECTURE decision log; assumptions go into the PRD.
- **Secrets.** Never committed, pasted into chat, or logged.
- **Dependencies.** Prefer fewer. Every new native dependency is checked on the dev machine before adoption.

## 10. Mapping from the source brief's phases

| Source phase | Milestones |
|---|---|
| 1 — Repository, environments, infrastructure | M1a (+ deploy in M2) |
| 2 — Auth, onboarding, dashboard | M1b–c, M2 |
| 3 — Roadmap and lesson generation | M3, M4 |
| 4 — Document ingestion and source-grounded content | M6 |
| 5 — Quizzes, explanations, saved attempts | M5 |
| 6 — Flashcards, reminders, resources | M7 |
| 7 — Exports and product quality | M8 |
| 8 — Deployment, observability, beta | M2 (skeleton), M9 |

The order differs from the source brief in one deliberate way: quizzes and mastery (M5) come **before** documents (M6), so the full learning loop is testable with real users earlier.
