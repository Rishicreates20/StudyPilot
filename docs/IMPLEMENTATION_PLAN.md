# StudyPilot — Implementation Plan

| | |
|---|---|
| **Status** | Draft v0.1 — planning complete, implementation not started |
| **Date** | 2026-10-09 |
| **Related** | [PRD.md](PRD.md) · [ARCHITECTURE.md](ARCHITECTURE.md) |

**Next action: Milestone 1 — Foundation + the Goals vertical slice** (§4).

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
| **M2** | Goal management, onboarding, first deploy | Edit/pause/complete/archive, profile settings, onboarding wizard, responsive app shell, **walking-skeleton deployment** | Vercel, Render, Supabase staging | — |
| **M3** | Job queue, AI foundation, roadmaps | Durable queue + worker, `LLMProvider`, intent parser + planner, programmatic plan validation, budgets + usage ledger, job-progress UI, roadmap overview | LLM API key; confirm provider (A4) | — |
| **M4** | Lessons and study workspace | Structured lessons per item, workspace UI, simple-explanation toggle, progress, resume | — | — |
| **M5** | Quizzes, mastery, next action | Question generation, server-side grading, answer-key isolation, mastery, weak-topic flags, next-action | — | **Private alpha** |
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

*Exit check:* one command runs lint + type-check + unit tests for both apps and passes ✅; both health endpoints respond ✅; no secret is tracked ✅; CI green on `main` ⏳ (pending first run).

**M1b — Data and API slice** *(commit boundary 2)* — **implemented; see status notes**

- [x] **Time-boxed spikes** (outcomes in the ARCHITECTURE decision log):
  - **S1** — role switching and claims inside a request transaction: verified on PostgreSQL 16 through psycopg 3 and a pool (ADR-006, ADR-021). Under Supabase's own roles: ⏳ CI job `supabase-stack`.
  - **S2** — JWT verification: both modes implemented with per-mode algorithm allow-lists and tested with real signatures; Supabase's docs checked on 2026-10-10. Which algorithm the local stack issues is detected in CI, not assumed. Genuine Supabase tokens: ⏳ CI.
  - **S3** — Next.js 16 uses `proxy.ts`; `@supabase/ssr` sessions are refreshed there with `getClaims()`. Verified by unit tests; the real refresh is exercised by the Playwright journey ⏳ CI.
  - **S4** — toolchain pinned in M1a (TypeScript 6.0.3, Next 16.4, `typescript-eslint` 8.71).
- [x] Migrations `20261009130000_profiles.sql` (extensions-free; `set_updated_at()`, `profiles`, `handle_new_user` trigger with backfill, RLS, explicit grants) and `20261009130100_learning_goals.sql` (check constraints, index, RLS, column-level grants, per-user ownership key).
- [x] Database tests (pytest on a real PostgreSQL 16 instead of pgTAP, ADR-022): owner can read and write only their own rows; another user cannot; `anon` has no access; constraints reject invalid rows; profile created on sign-up; guards that fail the build if a `public` table lacks RLS.
- [x] API: Pydantic schemas, psycopg repositories, services, routers (`/v1/me`, `/v1/goals`), `user_transaction`, cursor pagination, 404 on non-owned resources, per-user goal cap.
- [x] Tests: settings validation; JWT (valid, missing, malformed, expired, wrong audience/issuer/algorithm, bad signature, anonymous, non-UUID subject); JWKS cache behaviour; authorization (user B gets 404 on user A's goal); validation errors; pool isolation; failure handling. **250 pass, 1 skipped** (the genuine-stack module). No schema drift test: there are no ORM models (ADR-021).
- [x] OpenAPI export → `packages/contracts` (generated types) → `npm run contracts:check`; regeneration is deterministic. The CI step is wired ⏳ unobserved.

**M1c — Web slice** *(commit boundary 3)* — **implemented; see status notes**

- [x] Sign-up, sign-in, sign-out; HttpOnly cookie sessions refreshed in `proxy.ts`; protected `(app)` layout that re-checks the session; uniform "email or password is incorrect" message; "check your email" state when confirmation is on; a confirm route that refuses open redirects and unknown link types.
- [x] Dashboard: goals from the API with skeleton, empty state, and error state with retry; session-ended handling that cannot loop (ADR-024).
- [x] Create-goal form (native form + Server Action + Zod, not React Hook Form) showing server-side field errors; success returns to the dashboard with the new goal visible.
- [x] Vitest tests (283): redirect safety, schemas, messages, auth and goal Server Actions with only Supabase and the API mocked, the typed API client, the proxy and cookie hardening, the confirm route.
- [x] Playwright journey written (`apps/web/e2e`): sign up → create goal → reload → HttpOnly cookie check → sign out → blocked → sign in → **second user sees nothing**. ⏳ Not yet run anywhere: it needs the Supabase stack, which only CI can start.

**M1d — Review and documentation** *(commit boundary 4)*

- [x] Security pass. Ownership paths, grants and error bodies are covered by tests. **Bundle search (2026-10-10):** the web app was built with canary values for `DATABASE_URL`, the JWT secret, a service-role key and a secret key in its environment; none appears anywhere in the 422 files of `.next`, there are no JWT-shaped strings, and the browser bundle contains no Supabase client code and not even the publishable key (auth runs on the server). The only `sb_secret_` matches are the Supabase library's own key-prefix checks. Not done: a dependency-level review beyond `npm audit`.
- [ ] Accessibility pass (keyboard, focus, contrast) and a mobile-width pass on the new pages.
- [x] README, ARCHITECTURE (ADR-021…024, S1–S3 outcomes, ADR-006 status), `.env.example` files, `docs/SUPABASE_SETUP.md` and the configuration reference updated to match what exists.

*Status notes (what is and is not verified):* Run locally and observed: web typecheck, lint, formatting and 283 Vitest tests; production web build; API 250 pytest tests against a real PostgreSQL 16 and strict pyright with 0 errors; contract regeneration is byte-identical. **Not verified locally** (no Docker, and no Supabase project is connected to this repository): sign-up, sign-in, session persistence and sign-out against genuine Supabase Auth; Supabase's real roles and `auth` schema; the Playwright journey; the Docker images; the GitHub Actions workflow. Those are what the `supabase-stack` and `docker` jobs exist to prove, and they stay ⏳ until a run is observed.

### 4.4 Acceptance criteria

| # | Criterion | Evidence | Status |
|---|---|---|---|
| 1 | A new user can sign up and sign in; an unauthenticated call to a protected route returns **401** | 401 matrix in API tests; real sign-up/sign-in in the stack job and Playwright | 401 ✅ · sign-up/sign-in ⏳ CI |
| 2 | Creating a goal persists a row with `user_id` = the caller | API and database tests on real PostgreSQL | ✅ |
| 3 | The goal appears on the dashboard and survives a reload | Playwright | ⏳ CI |
| 4 | User B gets **404** for user A's goal; a database session acting as B cannot select A's rows | API and database tests; the same under Supabase's roles in the stack job | Real PostgreSQL ✅ · Supabase roles ⏳ CI |
| 5 | `anon` has no table access to application tables | Guard tests; stack job | ✅ locally · stack ⏳ CI |
| 6 | Invalid input produces field-level errors in the UI and a problem+json 422 | Web action and schema tests; API validation tests | ✅ |
| 7 | The dashboard shows skeleton, empty and error-with-retry states | Implemented; empty state exercised by the Playwright journey; the feedback, load-error and goal components have unit tests; the dashboard page itself has none | ◐ partly tested |
| 8 | Missing or invalid environment variables stop the API at startup without echoing secrets | Settings tests | ✅ |
| 9 | `/healthz` and `/readyz` behave correctly (readiness fails when the database is unreachable) | Health and failure tests | ✅ |
| 10 | The generated API client is in sync with the OpenAPI document (CI-enforced) | Deterministic regeneration observed locally; CI step wired | ✅ locally · CI ⏳ (no drift test: no ORM models) |
| 11 | Lint, type-check, unit, integration and E2E suites pass **in CI**, outputs read | — | ⏳ pending the first run with these changes |
| 12 | A new contributor can follow the README to a running app | `docs/SUPABASE_SETUP.md` written from Supabase's current docs | ⏳ not yet followed by someone fresh |

## 5. Later milestones in outline

Each gets its own detailed breakdown, written at the end of the previous milestone using what was learned.

**M2 — Goal management, onboarding, first deploy.** `PATCH`/archive/complete/pause goals · profile settings (name, locale, timezone) · onboarding wizard capturing level, daily time, target date, languages · responsive app shell and navigation · theme and Indic-font verification · **deploy the skeleton** to Vercel + Render + a staging Supabase project · CI migration-deploy job (staging automatic, production manual) · confirm pooler mode and IPv4/IPv6 behaviour on Render.

**M3 — Job queue, AI foundation, roadmap generation.** Migrations + pgTAP for `generation_jobs`, `ai_usage_events`, `roadmaps`, `roadmap_items`, `roadmap_item_prerequisites` · queue claim/lease/heartbeat/retry/cancel · worker process and compose service · `LLMProvider`, first real adapter, `FakeProvider` for tests · versioned prompts for intent parser and planner · **programmatic** plan validators (time budget, acyclic ordered prerequisites, objective coverage, unique sequence) with one bounded repair attempt · budgets and usage ledger · `Idempotency-Key` · job status API and progress UI · roadmap overview with learner edits · evaluation fixtures (malformed output, infeasible plans) · worker-kill and duplicate-submission tests. *Verify current provider SDK APIs and model names first.*

**M4 — Lessons and study workspace.** `learning_materials` · lesson schema and validator · per-item lesson job (on demand, with prefetch of the next item) · lesson renderer for structured JSON (headings, code, callouts, glossary) · simple-explanation toggle from stored content · item progress and resume position · mobile-first workspace · general-knowledge labelling when no sources exist.

**M5 — Quizzes, mastery, next action (private alpha gate).** Migrations + pgTAP for quizzes, questions, `question_answer_keys`, attempts, answers, `topic_mastery` · assessment generator and validators (one correct option, duplicate detection, objective mapping) · submit/grade endpoint with server-side scoring · results with explanations after submission only · deterministic mastery and weak-topic thresholds · next-action recommendation with reason · progress page · tests asserting no key/explanation leaks before submission.

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
