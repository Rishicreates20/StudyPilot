# CLAUDE.md — StudyPilot working agreement

Durable instructions for AI-assisted work in this repository. Keep this file short and accurate; update it when commands or conventions change.

## Status

Planning is complete; **no application code exists yet**. The next task is **Milestone 1** in `docs/IMPLEMENTATION_PLAN.md` §4. Do not build later milestones early.

## Read first

- `docs/PRD.md` — what and why; assumptions A1–A14
- `docs/ARCHITECTURE.md` — how; decision log (ADR-001…017); items marked **[verify]** must be checked against current official docs before use, **[spike]** items are time-boxed experiments
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
- Python: ruff, pyright, pytest. Web: ESLint, `tsc`, Vitest, Playwright.

*Commands will be listed here when Milestone 1 lands. Do not invent commands; document only ones that were run and worked.*

## Dev-environment gotchas (primary machine: Windows 11 Home)

- **Smart App Control is on.** Unsigned native code can be blocked. Test any new native dependency early. Never suggest disabling the setting.
- Long paths are disabled: work from a short path (for example `C:\dev\StudyPilot`), not from deeply nested app-data folders.
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
