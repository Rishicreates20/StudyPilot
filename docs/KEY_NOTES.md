# StudyPilot — key notes: requirements and improvements

Written 2026-10-23 from the review sessions of 2026-10-12 and a fresh look at the repository. Every claim says whether it was observed.

## Update 2026-10-29

- **CI was red everywhere, now fixed on `main`.** `main` failed its production `npm audit` from 2026-10-23 (Next.js 16.4.0, critical advisories), and a zod advisory (GHSA-mrhx-c7xc-m3w5, high, zod < 4.6.6) then failed every branch at `--audit-level=high`. #3 (Next.js 16.4.2, zod 4.6.7, robust API error bodies) and #4 (M7 flashcards, brought up to date with `main`) were merged after green runs 40904058055 and 40905780424 (all five jobs, read); #2 was closed as a duplicate of #3.
- **Flashcards (M7 first slice) are on `main`.** Its migration ran under a genuine Supabase stack in CI; it is **not applied to the hosted project** yet (needs the owner's go-ahead).
- **Exports (M8) are built** on `feat/m8-exports` (ADR-049), now merged with `main` and tested (API 2132 passed / 1 skipped, web 1177 passed, production build). The table in §1 below still says "schema only" for exports: that is out of date.
- **A Vercel project is connected to the repository** and its preview deployment failed on both #3 and #4. Its log could not be read from here (the Vercel connector has no access to that team); a likely cause, not verified, is missing `NEXT_PUBLIC_*` variables or a root directory other than `apps/web`.
- **Dev-only advisories:** `npm audit` without `--omit=dev` reports 10 (6 high), mostly under `shadcn`'s MCP SDK dependencies; CI gates production dependencies only.
- **Still parked:** the OpenAI-compatible provider exists as untracked files in the main checkout (failing ruff, pyright and one test), in `stash@{0}`, and as the pushed branch `origin/feat/ai-provider-chain` (no pull request). `DATABASE_URL` is now set in `services/api/.env` (checked by name only).

## 1. Where the app stands

| Area | State | Evidence |
|---|---|---|
| M1–M5: auth, goals, onboarding, roadmaps, lessons, quizzes, mastery | Built | 2026-10-12 local run: web 893/893 tests, API 1498 passed / 1 skipped, ruff + pyright + `tsc` + ESLint + Prettier clean, production build passed, no contract drift |
| CI on `c485854` and `7078fef` | All 5 jobs green | Read from the public GitHub Actions API |
| M6 documents | Built, pulled on 2026-10-23 | After the pull: web 980/980, API 1929 passed / 1 skipped, ruff/`tsc`/ESLint clean, production build and contract check passed; CI green on `318a07d` (all 5 jobs). Upload code reviewed for security, no code-level holes found |
| AI provider bench (PR #1) | Merged, pulled | Tests pass; not otherwise reviewed |
| Resources (YouTube) and exports migrations | **Schema only**: tables exist, no code | Recovered into the repo in `50d4e59`; see the notes in `IMPLEMENTATION_PLAN.md` under M7 and M8 |
| Web app on `:3000` | Running now | Public pages answer 200; `/status` correctly reports the API as unreachable |
| API and worker | **Not running** | `DATABASE_URL` is empty in `services/api/.env` |

## 2. What is needed to run the whole app (requirements)

1. **`DATABASE_URL`** in `services/api/.env`: the Supabase *session pooler* string (Dashboard → Connect) ending `?sslmode=require`. It holds the database password, so only the owner types it in. This is the one thing blocking a full run.
2. Already filled in (git-ignored files): `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`, `SUPABASE_URL`, `LLM_PROVIDER=fake`. The project signs tokens with ES256, so `SUPABASE_JWT_MODE=jwks` and no JWT secret is needed.
3. **For real AI content:** `LLM_PROVIDER=gemini` plus `GEMINI_API_KEY`. Fake mode only produces labelled samples.
4. **For M6 documents** (once the checkout is updated): the hosted project needs the `vector` extension and migration `20261012200000_documents.sql` applied; `SUPABASE_PUBLISHABLE_KEY` for the API; a private Storage bucket (or `DOCUMENT_STORAGE=local` for local runs only).
5. **Tooling on this machine:** `uv` (now installed). Inside the sandboxed desktop app, `uv` needed `UV_PYTHON_INSTALL_DIR` pointing outside `%APPDATA%` (worked on 2026-10-12; the note was reverted from `CLAUDE.md` at your request).
6. **A human:** sign-up/sign-in in the browser (an assistant must not type passwords), and for deployment the Vercel, Render and staging-Supabase accounts.

## 3. Repository housekeeping (do this before more work)

- This checkout is up to date with `origin/main` (pulled 2026-10-23).
- **Parked work:** edits to `config.py`, `factory.py`, `worker.py`, `llm_smoke.py` and two test files (an OpenAI-compatible provider) are saved in `git stash` (`stash@{0}`), with the untracked `app/ai/openai_compat.py` and its test still in the folder. Both untracked files currently fail ruff and pyright. Decide whether to restore, finish or drop them.
- **Migration drift (resolved on paper, open in substance):** the hosted database had two migrations that were never committed (`resources`, `exports`). The repo now has them (`50d4e59`), so the two agree, but the code for YouTube suggestions (M7) and exports (M8) is still missing, and the ADR-049 cited by `exports` was never written. Find that code before rebuilding it.
- `main` is public: never commit `.env*`.

## 4. Known gaps and improvements, in priority order

1. **Deploy a staging copy** (Vercel + Render + Supabase staging + a migration job). Not started; needs owner accounts. Without it nothing has been seen outside a laptop and CI.
2. **Judge real AI quality with a person.** Plans, lessons, quizzes, marking and retrieval are only checked for being valid, never for being good. The default Gemini model was overloaded on 2026-10-11, so its lessons are unobserved.
3. **Test M6 on genuine Supabase with real files.** Storage with real files, scans, handwriting and Hindi/Odia documents are unobserved; CI's stack excludes Storage.
4. **Free-tier AI limits.** About 20 requests per model per day on a free key; fallback models exist but a class-sized load will exhaust them. Plan a paid key and cost budgets (only a daily *count* limit exists today).
5. **Missing features by design:** flashcards, spaced revision, exports, document-grounded roadmaps, syllabus-by-URL, lesson prefetch, "make this lesson version current", an OpenAI adapter on `main`.
6. **Small defects and polish seen:** the plan's test counts drift (891 vs 893, now fixed); the status page looks stuck on "Checking services…" until the browser paints (an artifact of the review pane, not a server fault; worth a quick check in a normal browser); Playwright cannot run against a hosted project by design, so the browser journey is CI-only.
7. **Docs consistency:** `PRD.md`, `ARCHITECTURE.md` (ADR numbers), contracts and the plan must be re-read against the M6 code once it is pulled. `docs/StudyPilot_Project_Reference.pdf` is referenced in the working agreement but is not in the repository.

## 5. Security posture (reviewed, not guaranteed)

Checked in code on 2026-10-12: every quiz endpoint depends on the verified token, answer keys have no grant or policy and are read only by the grader at submission, submissions are validated before any key is read, and foreign resources return 404. Not re-reviewed: the M6 code (uploads, Storage, retrieval), which is the largest new attack surface.

## 6. Recommended next steps

1. Add `DATABASE_URL`, then start API + worker and walk the whole flow with the fake provider.
2. Resolve the 4-commit lag and the uncommitted provider edits, then re-run the full check suite on the merged code.
3. Review M6 for upload limits, bucket privacy and ownership.
4. Create the staging accounts and deploy.
5. Run a real Gemini session on one real document and have a person judge the output.
