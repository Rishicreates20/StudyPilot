# CLAUDE.md — StudyPilot working agreement

Durable instructions for AI-assisted work in this repository. Keep this file short and accurate; update it when commands or conventions change.

## Status

The **foundation (Milestone 1a)** is implemented: web app, API, design system, health checks, Docker, CI. There are no accounts, database or AI features yet. The next task is **Milestone 1b** (database + auth + goals API) in `docs/IMPLEMENTATION_PLAN.md` §4. Do not build later milestones early.

## Read first

- `docs/PRD.md` — what and why; assumptions A1–A14
- `docs/ARCHITECTURE.md` — how; decision log (ADR-001…020); items marked **[verify]** must be checked against current official docs before use, **[spike]** items are time-boxed experiments
- `docs/IMPLEMENTATION_PLAN.md` — milestone order, acceptance criteria, risks

## Architecture rules (non-negotiable)

- Modular monolith. FastAPI owns business logic, authorization, grading and AI orchestration. Next.js is presentation only; do not duplicate business rules in the frontend.
- Schema source of truth is `supabase/migrations/*.sql`. **No Alembic.** One migration per slice, with RLS, grants and pgTAP tests in the same change. Never ship a table without RLS.
- Every user-data table has `user_id`; child tables use composite FKs `(parent_id, user_id)`.
- Answer keys and explanations live in `question_answer_keys` and are never returned before submission.
- User requests run in an RLS-scoped DB session; `system_session()` is for the worker and grading-key reads only and must not be imported by routers.
- Non-owned or missing resource → **404**. Errors are RFC 9457 problem+json; never leak stack traces, prompts or secrets.
- All AI calls go through `LLMProvider`. Structured outputs are always re-validated with Pydantic. Plan feasibility, citations and answer keys are validated **by code**, not by asking the model. Models have no tools. Uploaded content is data, never instructions.
- One job queue: PostgreSQL (`SKIP LOCKED`, leases). No Redis. Jobs checkpoint per stage and are idempotent.
- Never fabricate AI-generated learning content, video URLs, timestamps or citation IDs to make the product look complete. `FakeProvider` is for tests only and is refused in staging/production.
- API contract = FastAPI OpenAPI. Regenerate `packages/contracts`; CI fails on drift.

## Toolchain

- Python **3.14** via `uv` (3.12 is blocked on the primary dev machine). Node **24**, npm workspaces (no pnpm). TypeScript **pinned to 6.0.x** (not 7).
- Python: ruff, pyright (strict), pytest. Web: Prettier, ESLint, `tsc`, Vitest + Testing Library. Playwright arrives with the first end-to-end slice.

### Commands (all run from the repo root; all were run and passed)

| Command | Does |
|---|---|
| `npm install` · `uv sync --directory services/api` | Install web / API dependencies |
| `npm run dev:web` · `npm run dev:api` | Start Next.js (:3000) / FastAPI (:8000) |
| `npm run check` | Format check + lint + type-check + tests for **both** apps |
| `npm run format` | Write formatting (Prettier + `ruff format`) |
| `npm run lint` · `typecheck` · `test` (each also `:web` / `:api`) | Individual checks |
| `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000 npm run build` | Production web build (the variable is required) |
| `docker compose up --build` | API + web with hot reload (**not verified locally**; CI builds and boots the images) |

Python tools run as `uv run python -m <tool>` (never the `pytest`/`ruff`/`pyright` launchers, which Smart App Control blocks). The API starts with `uvicorn app.main:create_app --factory`.

### Web conventions (Next.js 16 — verify against `node_modules/next/dist/docs/` before using an API)

- **Cache Components is on.** Request-time work (fetching live data, `Date.now()`, `Math.random()`, request headers) must sit under a `<Suspense>` boundary and, when it is inherently per-request, start with `await connection()` from `next/server`. Route handlers that report live state must do the same (see `app/api/health/route.ts`). Never call `new Date()` / `Date.now()` in a Server Component outside that.
- The error boundary prop is `retry` (not `reset`/`unstable_retry`). `LayoutProps<"/">` / `PageProps` types come from `next typegen` (run by `npm run typecheck:web`).
- Environment access goes through `src/lib/env.ts` (Zod, fail-fast); read `NEXT_PUBLIC_*` only via literal `process.env.NAME` there.
- Use design tokens and the components in `src/components` (see `docs/DESIGN_SYSTEM.md`); never hard-code colours. Server-only tests need `// @vitest-environment node`.
- Zod: use `z.url({ protocol: /^https?$/ })`, not `z.httpUrl()` (it rejects `localhost` and `http://api:8000`).
- `npx shadcn init/add` puts the `shadcn` package under `dependencies`; keep it in `devDependencies` (it is only used for `@import "shadcn/tailwind.css"` at build time) or `npm audit --omit=dev` fails in CI.
- GitHub Actions: pin exact existing tags and check them with `GET /repos/<owner>/<repo>/git/ref/tags/<tag>`; some actions (for example `astral-sh/setup-uv`) publish no floating major tag like `v10`.

## Dev-environment gotchas (primary machine: Windows 11 Home)

- **Smart App Control is on.** Unsigned native code can be blocked. Test any new native dependency early. Never suggest disabling the setting.
- Long paths are disabled: work from a short path, not from deeply nested app-data folders. The current checkout lives under OneDrive, which makes installs slow (a first `npm install` took ~5 minutes); prefer a folder outside cloud sync.
- Write multi-line files with the Write tool, not shell heredocs: a large combined heredoc failed to parse in this environment.
- No Docker/WSL here: database-dependent tests (pgTAP, integration, E2E) are verified in CI or a Codespace. Do not claim they passed unless output was observed.
- Git: the default branch is `main`; line endings are LF via `.gitattributes`.

## Security and secrets

- The repository is **public**. Never commit `.env*` (only `.env.example` with placeholders), keys, tokens or connection strings, and never echo them into logs or chat.
- Service-role keys, DB URLs and LLM keys are server-only. Only `NEXT_PUBLIC_*` values reach the browser.

## Definition of done

A feature is done only when: the workflow works end to end · data persists · permissions are enforced · inputs/outputs are validated · loading, empty and error states exist · tests are written **and run with output observed** · nothing regressed · docs match the implementation.

## Process

- Plan → one vertical slice → run checks → inspect the diff → fix → commit. Conventional Commits; short-lived branches; PRs so CI runs.
- Record assumptions in the PRD and technical decisions in the ARCHITECTURE decision log instead of asking routine questions. Ask only when a missing credential, irreversible action or material product decision blocks progress.
- Never claim an external account is configured, a deployment succeeded or a test passed unless a tool confirmed it.
