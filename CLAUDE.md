# CLAUDE.md — StudyPilot working agreement

Durable instructions for AI-assisted work in this repository. Keep this file short and accurate; update it when commands or conventions change.

## Status

**Milestones 1a–1c are implemented:** foundation, Supabase database and auth, protected goals API, and the web sign-up / sign-in / dashboard / create-goal flow. There are no AI features yet. The next task is **Milestone 2** (goal management, onboarding, first deployment) in `docs/IMPLEMENTATION_PLAN.md`. Do not build later milestones early.

What is *not* yet observed: anything that needs a genuine Supabase stack (real Auth tokens, Supabase's own roles, the Playwright journey) — only the CI `supabase-stack` job can run it. Do not describe those as verified until a CI run has been read.

## Read first

- `docs/PRD.md` — what and why; assumptions A1–A14
- `docs/ARCHITECTURE.md` — how; decision log (ADR-001…024); items marked **[verify]** must be checked against current official docs before use, **[spike]** items are time-boxed experiments
- `docs/IMPLEMENTATION_PLAN.md` — milestone order, acceptance criteria (with honest status), risks
- `docs/SUPABASE_SETUP.md` — how a Supabase project is configured and which environment variables exist

## Architecture rules (non-negotiable)

- Modular monolith. FastAPI owns business logic, authorization, grading and AI orchestration. Next.js is presentation only; do not duplicate business rules in the frontend.
- Schema source of truth is `supabase/migrations/*.sql`. **No Alembic, no ORM-generated DDL.** One migration per slice, with RLS, explicit grants and database tests in the same change. Never ship a table without RLS (a guard test fails the build). New `public` tables get Supabase's default grants, so every migration revokes them and grants back only what the API needs.
- Data access is psycopg 3 with explicit SQL (ADR-021), in `app/repositories`. Every user request runs inside `Database.user_transaction(principal)`, which assumes the `authenticated` role with the verified claims; repositories take the `UserConnection` it yields and **also** filter on `user_id`. Routers never obtain a connection any other way.
- **Identity comes only from the verified token** (`get_principal`). Never read a user ID from a body, query string, header or form field; request bodies use `extra="forbid"` so a field naming an owner is a 422. Test every new endpoint for: no token, bad token, another user's resource (404).
- Every user-data table has `user_id`; child tables use composite FKs `(parent_id, user_id)`.
- Answer keys and explanations live in `question_answer_keys` and are never returned before submission.
- `system_session()` (worker and grading-key reads only) does not exist yet; when it does it must not be imported by routers.
- Non-owned or missing resource → **404**. Errors are RFC 9457 problem+json; never leak stack traces, prompts, tokens or secrets. Never log tokens, emails, passwords or user-authored text.
- The Supabase **service-role / secret key is not used anywhere** and must not be added without a recorded decision. Only the publishable key is public.
- All AI calls go through `LLMProvider`. Structured outputs are always re-validated with Pydantic. Plan feasibility, citations and answer keys are validated **by code**, not by asking the model. Models have no tools. Uploaded content is data, never instructions.
- One job queue: PostgreSQL (`SKIP LOCKED`, leases). No Redis. Jobs checkpoint per stage and are idempotent.
- Never fabricate AI-generated learning content, video URLs, timestamps or citation IDs to make the product look complete. `FakeProvider` is for tests only and is refused in staging/production.
- API contract = FastAPI OpenAPI. After changing a route or schema run `npm run contracts:generate` and commit `packages/contracts`; CI fails on drift.

## Toolchain

- Python **3.14** via `uv` (3.12 is blocked on the primary dev machine; the test database helper in `services/api/tests/pg_server` is the one 3.12 exception). Node **24**, npm workspaces (no pnpm). TypeScript **pinned to 6.0.x** (not 7).
- Python: ruff, pyright (strict), pytest. Web: Prettier, ESLint, `tsc`, Vitest + Testing Library, Playwright (`apps/web/e2e`, CI only).

### Commands (all run from the repo root)

| Command | Does |
|---|---|
| `npm install` · `uv sync --directory services/api` · `uv sync --directory services/api/tests/pg_server` | Install web deps / API deps / the API tests' throwaway PostgreSQL |
| `npm run dev:web` · `npm run dev:api` | Start Next.js (:3000) / FastAPI (:8000, needs `services/api/.env`) |
| `npm run check` | Format check + lint + type-check + tests for **both** apps |
| `npm run format` | Write formatting (Prettier + `ruff format`) |
| `npm run lint` · `typecheck` · `test` (each also `:web` / `:api`) | Individual checks |
| `npm run contracts:generate` · `contracts:check` | Regenerate `packages/contracts` from the API / fail if it changed |
| `npm run build` | Production web build; needs `NEXT_PUBLIC_API_BASE_URL`, `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` |
| `docker compose up --build` | API + web with hot reload (**not verified locally**; CI builds and boots the images) |

Python tools run as `uv run python -m <tool>` (never the `pytest`/`ruff`/`pyright` launchers, which Smart App Control blocks). The API starts with `uvicorn app.main:create_app --factory`; on Windows it needs `--loop asyncio:SelectorEventLoop` (already in `dev:api`) because psycopg's async mode rejects the default proactor loop. If even the venv's `python.exe` is blocked (`os error 4551`), use the fallback in `docs/DEVELOPMENT.md` (base interpreter + `PYTHONPATH`); `ruff` then cannot run locally, so say so rather than claiming a lint pass.

### Web conventions (Next.js 16 — verify against `node_modules/next/dist/docs/` before using an API)

- **Cache Components is on.** Request-time work (fetching live data, `Date.now()`, `Math.random()`, request headers, cookies) must sit under a `<Suspense>` boundary and, when it is inherently per-request, start with `await connection()` from `next/server`. Route handlers that report live state must do the same (see `app/api/health/route.ts`). Never call `new Date()` / `Date.now()` in a Server Component outside that.
- The error boundary prop is `retry` (not `reset`/`unstable_retry`). `LayoutProps<"/">` / `PageProps` types come from `next typegen` (run by `npm run typecheck:web`). The request interceptor is `src/proxy.ts` (not `middleware.ts`).
- **Auth:** sessions are server-side only. Never add `createBrowserClient` or store a token in `localStorage`/`sessionStorage`: the session cookies are written `HttpOnly` by `src/lib/supabase/cookies.ts` and the browser client could not read them. Decide who someone is with `getClaims()` (verifies the signature), never `getSession()`. The proxy is UX only; every protected page re-checks the session and the API verifies the token.
- **Redirects:** run every `next`/return-to value through `safeRedirectPath`. When the API rejects a session Supabase still holds, redirect with `sessionEndedUrlFor` (the sign-in page shows its form for that marker); a plain `signInUrlFor` there would loop.
- **Forms:** native forms → Server Actions → Zod → API; map the API's field errors back onto inputs; never echo a password in returned state; use one generic message for failed sign-in (no account enumeration).
- Environment access goes through `src/lib/env.ts` (Zod, fail-fast); read `NEXT_PUBLIC_*` only via literal `process.env.NAME` there.
- Use design tokens and the components in `src/components` (see `docs/DESIGN_SYSTEM.md`); never hard-code colours. Server-only tests need `// @vitest-environment node`.
- Zod: use `z.url({ protocol: /^https?$/ })`, not `z.httpUrl()` (it rejects `localhost` and `http://api:8000`).
- `npx shadcn init/add` puts the `shadcn` package under `dependencies`; keep it in `devDependencies` (it is only used for `@import "shadcn/tailwind.css"` at build time) or `npm audit --omit=dev` fails in CI.
- GitHub Actions: pin exact existing tags and check them with `GET /repos/<owner>/<repo>/git/ref/tags/<tag>`; some actions (for example `astral-sh/setup-uv`) publish no floating major tag like `v10`.

## Dev-environment gotchas (primary machine: Windows 11 Home)

- **Smart App Control is on and its verdicts change.** Unsigned native code can be blocked, including things that ran the day before (2026-10-10: the venv launcher and `ruff.exe`). Test any new native dependency early. Never suggest disabling the setting.
- Long paths are disabled: work from a short path, not from deeply nested app-data folders. The current checkout lives under OneDrive, which makes installs slow (a first `npm install` took ~5 minutes); prefer a folder outside cloud sync.
- Write multi-line files and any script containing template strings or backticks with the Write tool, not shell `-e`/heredocs: quoting mangled backticks here more than once. Small heredocs without backticks are fine.
- No Docker/WSL here. The API's database tests *do* run locally (real PostgreSQL 16 via `pgserver`), but genuine-Supabase tests and the Playwright journey run only in CI. Do not claim they passed unless output was observed.
- Git: the default branch is `main`; line endings are LF via `.gitattributes`.

## Security and secrets

- The repository is **public**. Never commit `.env*` (only `.env.example` with placeholders), keys, tokens or connection strings, and never echo them into logs or chat.
- DB URLs, JWT secrets and LLM keys are server-only. Only `NEXT_PUBLIC_*` values reach the browser, and the production bundle must be checked for leaks when auth or env handling changes (see the bundle search in `docs/IMPLEMENTATION_PLAN.md` M1d).

## Definition of done

A feature is done only when: the workflow works end to end · data persists · permissions are enforced · inputs/outputs are validated · loading, empty and error states exist · tests are written **and run with output observed** · nothing regressed · docs match the implementation.

## Process

- Plan → one vertical slice → run checks → inspect the diff → fix → commit. Conventional Commits; short-lived branches; PRs so CI runs.
- Record assumptions in the PRD and technical decisions in the ARCHITECTURE decision log instead of asking routine questions. Ask only when a missing credential, irreversible action or material product decision blocks progress.
- Never claim an external account is configured, a deployment succeeded or a test passed unless a tool confirmed it.
