# StudyPilot

An AI-powered **personal learning coach**. A learner states a goal (a topic, an exam, a certification) or provides study material; StudyPilot builds a personalised roadmap, teaches each topic with structured lessons, tests understanding with quizzes, finds weak spots, and adapts what to study next.

> **Status: accounts, goals, AI roadmaps, lessons and quizzes.** You can sign up, set up your study preferences, create a learning goal, see it on your dashboard, edit it, pause, complete or archive it, and find it again after a refresh. From a goal you can **generate a personalised study roadmap**: a background worker asks an AI planner (Gemini) for a structured plan, the server checks it against your daily minutes and target date, and stores it as a versioned roadmap you can revise without losing earlier versions. Everything is backed by Supabase Auth and PostgreSQL with Row Level Security. Open any topic of a roadmap to have a **lesson** written for it in the background (objectives, sections with text, lists, code and callouts, key terms, worked examples, common mistakes, a summary and a simple explanation), study it with a contents panel, tick sections off, ask for a **simpler explanation** or another version (simpler, more examples, deeper), and come back later to find your place saved. Then **check what you learned**: a quiz is written from the lesson, graded on the server (the right answers never reach your browser before you submit), explained question by question, and turned into a **topic-by-topic mastery** score so you can see which parts are weak and get a relevant next step. Uploads arrive in the next milestones ([plan](docs/IMPLEMENTATION_PLAN.md)). Nothing in the UI is fake user data; the one stand-in, a labelled "Sample plan" from `LLM_PROVIDER=fake`, is for development and tests only.

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

To generate roadmaps, also run the background worker (third terminal) and give the API an AI provider in `services/api/.env`:

```bash
npm run dev:worker   # runs queued roadmap, lesson, quiz and marking jobs
```

Set `LLM_PROVIDER=gemini` and your own `GEMINI_API_KEY` (typed into that git-ignored file, never into chat or Git); or use `LLM_PROVIDER=fake` to try the whole flow with a clearly labelled sample plan and no key. Details: [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md#run).

| URL | |
|---|---|
| <http://localhost:3000> | Landing page |
| <http://localhost:3000/sign-up> · `/sign-in` | Create an account · sign in |
| <http://localhost:3000/onboarding> | Three-step setup for new accounts (every step can be skipped) |
| <http://localhost:3000/dashboard> | Your goals: in progress, completed, counts (needs sign-in) |
| <http://localhost:3000/goals/new> · `/goals/archived` | Create a goal · archived goals (restore or delete) |
| `/goals/<id>/learn/<topic>` | The study page of one topic: its lesson, contents, progress, neighbouring topics and its quiz card |
| `/goals/<id>/learn/<topic>/quiz/<quiz>` · `/results/<attempt>` | Take a quiz · its results: score, explanations, mastery, weak parts, next step |
| `/goals/<id>` · `/goals/<id>/roadmap` | A goal with its roadmap section · the roadmap: overview, modules, topics, schedule, versions |
| <http://localhost:3000/settings> | Name, language, time zone and default study preferences |
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
| Background work | One PostgreSQL-backed durable job queue (`FOR UPDATE SKIP LOCKED`, leases, retries) and a worker process |
| AI | Gemini over its REST API behind an `LLMProvider` interface (a labelled `fake` provider for tests); OpenAI *(planned)* |
| Tests | Vitest + Testing Library, pytest against a real PostgreSQL, Playwright |
| CI | GitHub Actions (API, web, genuine Supabase stack, Docker, secret scan) |
| Hosting *(planned)* | Vercel (web), Render (API + worker), Supabase (managed) |

## Repository layout

```
apps/web             Next.js application (auth, onboarding, dashboard, goals, settings) and its Playwright tests (e2e/)
services/api         FastAPI application (auth, goals, profile, roadmaps and jobs, health), the AI layer (`app/ai`), the background worker (`app/jobs`, `app/worker.py`) and their tests
packages/contracts   TypeScript types generated from the API's OpenAPI document
supabase/            Database migrations (the schema's source of truth), local-stack config
docs/                Product and engineering documentation
.github/             CI workflow and helper scripts
docker-compose.yml   Local stack (API + web)
```

Planned, not yet created: `apps/mobile`. See [ARCHITECTURE §3](docs/ARCHITECTURE.md#3-repository-structure).

## What is implemented

- **Accounts:** sign-up, sign-in, sign-out and session refresh with Supabase Auth. Sessions live in server-written HttpOnly cookies; the app never uses Supabase's browser client and never stores a token in script-readable storage. Pages that need an account are protected by the proxy **and** re-checked on the server; the API verifies the access token on every call.
- **Learning goals:** title, description, type (academic subject, examination, certification, professional skill, interview preparation, or general), current level, optional target date, daily study minutes, preferred languages (English, Hindi, Odia) and learning preferences (examples, quizzes, revision). A goal can be edited, paused and resumed, completed and reopened, archived and restored; only an archived goal can be deleted, and an archived goal is read-only. The rules are enforced by the database as well as the API.
- **AI roadmaps:** "Generate roadmap" queues a job and returns at once; the page shows live progress. The planner (prompt `roadmap-planner/v1`) is given your level, daily minutes, target date, languages and preferences, with your own words fenced off as data. Its plan has an overview, target outcome, objectives, ordered modules and topics with prerequisites, minutes and day numbers, practice tasks, revision sessions and optional extras, and it says what it assumed and what you should verify (it never presents itself as an official syllabus). **The server, not the model, checks the schedule**: no day exceeds your daily minutes, nothing runs past your target date, prerequisites come first, every objective is taught. One repair attempt, then a clear failure with a retry. Plans are stored as immutable versions: revising or regenerating adds a version, earlier ones stay and can be made current again. Transient AI failures retry with backoff; a crashed worker's job is recovered; a retry never stores a second roadmap.
- **Lessons and the study workspace:** each lesson is a typed, versioned document written by the worker (prompt `lesson-writer/v1`, your level and what you have already covered as context, everything you typed fenced as data) and checked by code before it is stored: no empty sections, no links, no citations of material you never supplied, the right language, a sensible length. Without your own material it says it is written from general knowledge. The page shows a contents panel (sections and all topics, with what is done), a sticky progress bar and a Contents sheet on phones, **Explain simply** (stored with the lesson, instant), **Write another version** (simpler, more examples, deeper, with an optional note; earlier versions stay readable), previous and next topic, and **resume**: your place is saved as you read and offered again when you return. A topic counts as finished once you finish a version of its lesson; the roadmap and the goal page show how many topics you have finished.
- **Quizzes, results and mastery:** from a topic with a lesson, "Take a quiz" queues a job; the worker writes about five questions (multiple choice, true/false and at most one short answer; prompt `quiz-writer/v1`) from the lesson, each tied to a learning objective and a difficulty, and code checks them before they are stored: exactly one correct option, no duplicate or repeated questions, no "all of the above", no answer hidden in the question, an explanation that does not defend a wrong option. **The answer key lives in a table no browser-facing role can read**; the quiz you receive has questions and options only. You submit once; multiple-choice and true/false are graded by code, and the right answer, why, and a note on each option appear in the results. A **short answer** is marked in the background against a rubric: the AI only says which rubric points you made, the points are added up by code, the result is labelled **AI estimate**, and you can tick the points you really covered, which overrides the estimate. Your **mastery** of a topic is a transparent score (newer quizzes weigh more, harder questions weigh more; below 70% needs practice, from 90% mastered, both configurable) with a score per learning objective, so a weak *part* shows. A low score gives a **practice quiz aimed at the weakest objectives** after going over the lesson again, never a restart of the course. The goal page lists every topic with its band, and the dashboard shows where you stand on each active goal and what to do next.
- **Onboarding and preferences:** a short three-step wizard (about you, how you like to study, your first goal) where nothing but the goal's title is required; the answers are saved as your defaults and can be changed in Settings. Goals you create later start from those defaults.
- **Protected API (`/v1`):** `GET|PATCH /v1/me`, `POST /v1/me/onboarding/complete`, `POST|GET /v1/goals`, `GET /v1/goals/summary`, `GET|PATCH|DELETE /v1/goals/{id}`, `PUT /v1/goals/{id}/status`, `POST|GET /v1/goals/{id}/roadmaps`, `GET /v1/goals/{id}/jobs`, `GET /v1/roadmaps/{id}`, `POST /v1/roadmaps/{id}/make-current`, `GET /v1/jobs/{id}`, `POST /v1/jobs/{id}/cancel|retry`, `POST /v1/roadmap-items/{id}/lessons`, `GET /v1/roadmap-items/{id}/study`, `PUT /v1/lessons/{id}/progress`, `POST|GET /v1/roadmap-items/{id}/quizzes`, `GET /v1/roadmap-items/{id}/assessment`, `GET /v1/quizzes/{id}`, `POST /v1/quizzes/{id}/attempts`, `GET /v1/quiz-attempts/{id}`, `POST /v1/quiz-attempts/{id}/regrade`, `PUT /v1/quiz-answers/{id}/review`, `GET /v1/goals/{id}/progress`. The caller's identity comes only from a verified token. Another user's goal answers 404. Request bodies that name an owner are rejected.
- **Database:** migrations for `profiles` (created automatically at sign-up), `learning_goals` and the goal lifecycle, with Row Level Security, explicit grants and constraints. Every user request runs in a transaction that assumes the `authenticated` role with the verified claims, so a missing filter in code still cannot leak another user's rows.
- **Web:** landing, sign-up, sign-in, onboarding, dashboard with real counts and lists, create/view/edit goal pages with confirmation for archive and delete, archived goals, settings, design system, status page, fail-fast environment validation, loading/empty/error states, and a layout that works from phone width up. The automated accessibility audit (axe-core, WCAG 2.2 AA, light and dark, phone and desktop) found no violations.
- **Tooling:** Prettier, ESLint, `tsc`, ruff, pyright (strict), Vitest, pytest, Playwright, one `npm run check`, Dockerfiles, Compose, CI.

## Security

Never commit secrets. `.env*` files are git-ignored; only `.env.example` files with placeholders are tracked, and only `NEXT_PUBLIC_*` values reach the browser. The Supabase **service-role / secret key is not used anywhere** and must not be added. The repository is public. See [ARCHITECTURE §5 and §13](docs/ARCHITECTURE.md#5-authentication-and-authorization) and [docs/SUPABASE_SETUP.md §7](docs/SUPABASE_SETUP.md#7-security-reminders).

## Licence

Not yet chosen. Until a licence file is added, all rights are reserved by default.
