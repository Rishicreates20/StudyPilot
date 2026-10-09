# StudyPilot

An AI-powered **personal learning coach**. A learner states a goal (a topic, an exam, a certification) or provides study material; StudyPilot builds a personalised roadmap, teaches each topic with structured lessons, tests understanding with quizzes, finds weak spots, and adapts what to study next.

> **Status: application foundation.** The web app, API, design system, health checks, Docker setup and CI exist and run. There are **no accounts, goals or AI features yet**: those arrive in the next milestones ([plan](docs/IMPLEMENTATION_PLAN.md)). Nothing in the UI is fake user data.

"StudyPilot" is a working name and is configurable.

## Quickstart

Prerequisites: **Git**, **Node 24** (npm 11), **[uv](https://docs.astral.sh/uv/)** (provides Python 3.14). Details and troubleshooting: [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).

```bash
git clone https://github.com/Rishicreates20/StudyPilot.git
cd StudyPilot

npm install                         # web dependencies
uv sync --directory services/api    # API dependencies
```

Run the two services (separate terminals). No configuration is needed locally:

```bash
npm run dev:api    # http://localhost:8000   (API docs at /docs)
npm run dev:web    # http://localhost:3000
```

| URL | |
|---|---|
| <http://localhost:3000> | Landing page |
| <http://localhost:3000/status> | Live web + API health |
| <http://localhost:3000/design> | Design system preview |
| <http://localhost:8000/healthz> · `/readyz` | API liveness · readiness |
| <http://localhost:3000/api/health> | Web liveness |

Verify everything (format, lint, types, tests for web and API):

```bash
npm run check
```

With Docker (API + web with hot reload):

```bash
docker compose up --build
```

## Documentation

| Document | What it covers |
|---|---|
| [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) | Install, run, test, Docker, configuration reference, troubleshooting |
| [docs/DESIGN_SYSTEM.md](docs/DESIGN_SYSTEM.md) | Tokens, components, accessibility rules |
| [docs/PRD.md](docs/PRD.md) | Vision, personas, priorities (P0–P2), requirements, assumptions |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | System design, data model, auth, job queue, AI layer, decisions |
| [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md) | Milestones M1–M9, risks, credentials needed |
| [CLAUDE.md](CLAUDE.md) | Working agreement for AI-assisted development |

## Technology

| Layer | Choice |
|---|---|
| Web | Next.js 16 (App Router, Cache Components), React 19, TypeScript (strict), Tailwind CSS 4, shadcn/ui |
| API | Python 3.14, FastAPI, Pydantic, structlog |
| Data and auth *(next milestone)* | Supabase Auth, PostgreSQL with row-level security, pgvector, private Storage |
| Background work *(planned)* | One PostgreSQL-backed durable job queue and a worker process |
| AI *(planned)* | Configurable LLM provider (Gemini or OpenAI) behind an `LLMProvider` interface |
| Tests | Vitest + Testing Library, pytest |
| CI | GitHub Actions |
| Hosting *(planned)* | Vercel (web), Render (API + worker), Supabase (managed) |

## Repository layout

```
apps/web            Next.js application (UI, design system, pages)
services/api        FastAPI application (health, config, errors, logging)
docs/               Product and engineering documentation
.github/workflows   CI
docker-compose.yml  Local stack (API + web)
```

Planned, not yet created: `supabase/` (migrations, the schema's source of truth), `packages/contracts` (typed API client), `apps/mobile`, `e2e/`. See [ARCHITECTURE §3](docs/ARCHITECTURE.md#3-repository-structure).

## What is implemented

- **Web:** responsive layout with skip link, header navigation and mobile drawer, light/dark/system theme, design tokens with automated WCAG contrast tests, reusable components (buttons, cards, inputs, dialogs, navigation, progress bar and ring, alerts, skeletons, empty/loading/error states), pages for landing, status and design preview, `/api/health`, not-found and error boundaries, fail-fast environment validation.
- **API:** application factory, validated settings (exit code 78 with a clear message on bad config), structured logging with request IDs, RFC 9457 problem+json errors, CORS allow-list, `/healthz` and `/readyz` with a pluggable readiness-check registry.
- **Tooling:** Prettier, ESLint, `tsc`, ruff, pyright (strict), Vitest, pytest, one `npm run check` command, Dockerfiles, Compose, CI.

## Security

Never commit secrets. `.env*` files are git-ignored; only `.env.example` files with placeholders are tracked, and only `NEXT_PUBLIC_*` values reach the browser. The repository is public. See [ARCHITECTURE §13](docs/ARCHITECTURE.md#13-security-privacy-and-threat-notes).

## Licence

Not yet chosen. Until a licence file is added, all rights are reserved by default.
