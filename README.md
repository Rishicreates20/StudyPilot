# StudyPilot

An AI-powered **personal learning coach**. A learner states a goal (a topic, an exam, a certification) or provides study material; StudyPilot builds a personalised roadmap, teaches each topic with structured lessons, tests understanding with quizzes, finds weak spots, and adapts what to study next.

> **Status: planning complete, implementation not started.** This repository currently contains the product and engineering plan only. There is no runnable application yet, and no command below that says "planned" works today. The first build milestone is described in [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md#4-milestone-1--foundation--goals-vertical-slice).

"StudyPilot" is a working name and is configurable.

## Documentation

| Document | What it covers |
|---|---|
| [docs/PRD.md](docs/PRD.md) | Vision, personas, priorities (P0–P2), functional requirements with acceptance criteria, non-functional requirements, metrics, assumptions |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | System design, repository structure, auth model, data model and migration strategy, job queue, AI layer, security, testing, dev environment, decision log |
| [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md) | Environment findings, milestones M1–M9, the exact first milestone, credentials needed, risk register |
| [CLAUDE.md](CLAUDE.md) | Working agreement for AI-assisted development in this repository |

## Product priorities

| Priority | Scope |
|---|---|
| **P0 — Core loop** | Auth · learning goals · async roadmap generation · structured lessons · study workspace with resume · quizzes with server-side grading · mastery and next action |
| **P1 — Learning loop** | Document upload + RAG with citations · OCR · flashcards (spaced repetition) · YouTube recommendations · adaptive roadmaps · reminders and streaks |
| **P2 — Expansion** | PDF/PPT export · Hindi/Odia improvements · Expo mobile apps · subscriptions · offline study · more exam verticals |

## Technology

| Layer | Choice |
|---|---|
| Web | Next.js (App Router), React, TypeScript (strict), Tailwind CSS, shadcn/ui |
| API | Python 3.14, FastAPI, Pydantic, SQLAlchemy 2.x |
| Data and auth | Supabase Auth, PostgreSQL with row-level security, pgvector, private Supabase Storage |
| Background work | One PostgreSQL-backed durable job queue and a worker process |
| AI | Configurable LLM provider (Gemini or OpenAI) behind an `LLMProvider` interface; structured outputs validated by Pydantic; RAG |
| Hosting | Vercel (web), Render (API + worker), Supabase (managed) |
| Mobile (later) | Expo / React Native using the same API contract |

## Planned repository layout

```
apps/web            Next.js application
apps/mobile         Expo application (later)
services/api        FastAPI API + worker (one Python package)
packages/contracts  TypeScript types/client generated from the API's OpenAPI document
supabase/           Migrations (source of truth for the schema), pgTAP tests, seed
e2e/                Playwright end-to-end tests
docs/               Product and engineering documentation
```

Directories are created by the milestone that first needs them. See [ARCHITECTURE §3](docs/ARCHITECTURE.md#3-repository-structure).

## Prerequisites (for when implementation starts)

- **Git**, **Node 24** with npm, **`uv`** (which provides **Python 3.14**)
- A **Supabase** account and a development project
- Optional: **Docker** (local Supabase stack), or a GitHub Codespace

Accounts and API keys needed per milestone are listed in [IMPLEMENTATION_PLAN §6](docs/IMPLEMENTATION_PLAN.md#6-external-services-accounts-and-credentials).

### Windows notes

- Use a **short checkout path** such as `C:\dev\StudyPilot`; Windows long-path support is typically off and `node_modules` nests deeply.
- **Smart App Control** can block unsigned native binaries. Python 3.14 via `uv` is the verified-working combination; see [ARCHITECTURE §15](docs/ARCHITECTURE.md#15-development-environment).
- The repository normalises line endings to LF (`.gitattributes`).

## Quickstart

*Planned — arrives with Milestone 1. This section will be replaced with commands that have been run and observed to work.*

## Security

Never commit secrets. `.env*` files are git-ignored; only `.env.example` files with placeholders are tracked. The repository is public. See [ARCHITECTURE §13](docs/ARCHITECTURE.md#13-security-privacy-and-threat-notes).

## Licence

Not yet chosen. Until a licence file is added, all rights are reserved by default.
