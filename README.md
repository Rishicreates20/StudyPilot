# StudyPilot

An AI-powered **personal learning coach**. A learner states a goal (a topic, an exam, a certification) or provides study material; StudyPilot builds a personalised roadmap, teaches each topic with structured lessons, tests understanding with quizzes, finds weak spots, and adapts what to study next.

> **Status: accounts, database and goals.** Sign-up, sign-in, sessions, a protected API and learning goals exist, backed by Supabase Auth and PostgreSQL with Row Level Security. There are **no AI features yet**; those arrive in the next milestones ([plan](docs/IMPLEMENTATION_PLAN.md)). Nothing in the UI is fake user data.

"StudyPilot" is a working name and is configurable.

## Quickstart

Prerequisites: **Git**, **Node 24** (npm 11), **[uv](https://docs.astral.sh/uv/)** (provides Python 3.14), and a **Supabase project** (free tier is fine). Details and troubleshooting: [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).

```bash
git clone https://github.com/Rishicreates20/StudyPilot.git
cd StudyPilot

npm install                         # web dependencies
uv sync --directory services/api    # API dependencies
```

**Configure Supabase** (once). Follow [docs/SUPABASE_SETUP.md](docs/SUPABASE_SETUP.md): create a project, apply the migrations with `npx supabase db push`, then copy two small files and fill in the values it tells you to:

```bash
cp services/api/.env.example services/api/.env      # DATABASE_URL, SUPABASE_URL, SUPABASE_JWT_MODE …
cp apps/web/.env.example apps/web/.env.local        # NEXT_PUBLIC_SUPABASE_URL, …_PUBLISHABLE_KEY
```

Run the two services (separate terminals):

```bash
npm run dev:api    # http://localhost:8000   (API docs at /docs)
npm run dev:web    # http://localhost:3000
```

| URL | |
|---|---|
| <http://localhost:3000> | Landing page |
| <http://localhost:3000/sign-up> · `/sign-in` | Create an account · sign in |
| <http://localhost:3000/dashboard> | Your goals (needs sign-in) |
| <http://localhost:3000/status> | Live web + API health |
| <http://localhost:3000/design> | Design system preview |
| <http://localhost:8000/healthz> · `/readyz` | API liveness · readiness (includes the database) |
| <http://localhost:8000/v1/me> | Protected: returns 401 without a valid token |

Without the Supabase values the web app still runs, but sign-up and sign-in show a "Sign-in isn't set up yet" notice, and the API refuses to start (it names the missing variables).

Verify everything that runs without Docker (format, lint, types, tests for web and API; the API tests start a real PostgreSQL):

```bash
uv sync --directory services/api/tests/pg_server    # one-off: the test database
npm run check
```

With Docker (API + web with hot reload, against a hosted Supabase project):

```bash
docker compose up --build
```

## Documentation

| Document | What it covers |
|---|---|
| [docs/SUPABASE_SETUP.md](docs/SUPABASE_SETUP.md) | **Connect a Supabase project**: settings, keys, connection string, migrations, every environment variable |
| [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) | Install, run, test, Docker, troubleshooting |
| [docs/DESIGN_SYSTEM.md](docs/DESIGN_SYSTEM.md) | Tokens, components, accessibility rules |
| [docs/PRD.md](docs/PRD.md) | Vision, personas, priorities (P0–P2), requirements, assumptions |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | System design, data model, auth, job queue, AI layer, decisions |
| [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md) | Milestones M1–M9, risks, credentials needed |
| [CLAUDE.md](CLAUDE.md) | Working agreement for AI-assisted development |

## Technology

| Layer | Choice |
|---|---|
| Web | Next.js 16 (App Router, Cache Components), React 19, TypeScript (strict), Tailwind CSS 4, shadcn/ui, `@supabase/ssr` |
| API | Python 3.14, FastAPI, Pydantic, psycopg 3 (explicit SQL), PyJWT, structlog |
| Data and auth | Supabase Auth, PostgreSQL with Row Level Security; pgvector and private Storage *(later)* |
| API contract | OpenAPI → generated TypeScript types (`packages/contracts`), checked for drift in CI |
| Background work *(planned)* | One PostgreSQL-backed durable job queue and a worker process |
| AI *(planned)* | Configurable LLM provider (Gemini or OpenAI) behind an `LLMProvider` interface |
| Tests | Vitest + Testing Library, pytest against a real PostgreSQL, Playwright |
| CI | GitHub Actions (API, web, genuine Supabase stack, Docker, secret scan) |
| Hosting *(planned)* | Vercel (web), Render (API + worker), Supabase (managed) |

## Repository layout

```
apps/web             Next.js application (UI, auth pages, dashboard) and its Playwright tests (e2e/)
services/api         FastAPI application (auth, goals, profile, health) and its tests
packages/contracts   TypeScript types generated from the API's OpenAPI document
supabase/            Database migrations (the schema's source of truth), local-stack config
docs/                Product and engineering documentation
.github/             CI workflow and helper scripts
docker-compose.yml   Local stack (API + web)
```

Planned, not yet created: `apps/mobile`, the job worker. See [ARCHITECTURE §3](docs/ARCHITECTURE.md#3-repository-structure).

## What is implemented

- **Accounts:** sign-up, sign-in, sign-out and session refresh with Supabase Auth. Sessions live in server-written HttpOnly cookies; the app never uses Supabase's browser client and never stores a token in script-readable storage. Pages that need an account are protected by the proxy **and** re-checked on the server; the API verifies the access token on every call.
- **Protected API (`/v1`):** `GET /v1/me`, `POST|GET /v1/goals`, `GET /v1/goals/{id}`. The caller's identity comes only from a verified token. Another user's goal answers 404. Request bodies that name an owner are rejected.
- **Database:** migrations for `profiles` (created automatically at sign-up) and `learning_goals`, with Row Level Security, explicit grants and constraints. Every user request runs in a transaction that assumes the `authenticated` role with the verified claims, so a missing filter in code still cannot leak another user's rows.
- **Web:** landing, sign-up, sign-in, dashboard of your goals, create-goal form, design system, status page, fail-fast environment validation, loading/empty/error states.
- **Tooling:** Prettier, ESLint, `tsc`, ruff, pyright (strict), Vitest, pytest, Playwright, one `npm run check`, Dockerfiles, Compose, CI.

## Security

Never commit secrets. `.env*` files are git-ignored; only `.env.example` files with placeholders are tracked, and only `NEXT_PUBLIC_*` values reach the browser. The Supabase **service-role / secret key is not used anywhere** and must not be added. The repository is public. See [ARCHITECTURE §5 and §13](docs/ARCHITECTURE.md#5-authentication-and-authorization) and [docs/SUPABASE_SETUP.md §7](docs/SUPABASE_SETUP.md#7-security-reminders).

## Licence

Not yet chosen. Until a licence file is added, all rights are reserved by default.
