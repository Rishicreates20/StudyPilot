# Deploying StudyPilot to staging

**Status (2026-11-01): nothing here has been run.** `render.yaml` is a prepared, unapplied Blueprint. No staging project, Render service or Vercel project exists. Do not describe anything below as done until a tool or the owner has confirmed it. Variable names and meanings: `docs/SUPABASE_SETUP.md` §4.

## Decisions the owner must make first

| # | Decision | Why it matters | Default if none given |
|---|---|---|---|
| 1 | **A new staging Supabase project, or reuse the existing hosted one?** | The existing project is the development project and holds test accounts. | New project (keeps staging clean and lets migrations be proven from zero) |
| 2 | **Region** (one for Supabase, Render and, ideally, Vercel functions) | Every request crosses API ↔ database; a mismatch adds latency. `render.yaml` assumes `singapore`. | Match whatever Supabase region is chosen |
| 3 | **Paid Render plans** (API + always-on worker, `0.5c-512mb` each) | A background worker has no free plan; without it no roadmap, lesson, quiz, document or export job ever runs. | Both paid. Check the current price on Render's pricing page before creating them |
| 4 | **Gemini key and spending cap** | Free-tier keys allow ~20 requests per model per day, so staging will hit `AI_QUOTA_EXHAUSTED` quickly. | Free key for a first smoke test only |

## Order of work (who does what)

1. **Owner:** create the staging Supabase project; note the project URL, publishable key, session-pooler connection string. Choose JWT signing keys (`jwks`).
2. **Apply migrations** (`supabase/migrations/*.sql`, in order) to staging. Only after the owner confirms the target project. Afterwards check the security advisor and that `question_answer_keys` has no grant for `anon`/`authenticated`.
3. **Storage:** confirm the private `documents` and `exports` buckets and their policies exist. **Supabase Storage has never been run for real** (only on a mock transport), so this is the first real test of it.
4. **Auth settings:** set Site URL and Redirect URLs to the Vercel address (otherwise confirmation links point at the wrong place).
5. **Owner:** create the Render account, connect the GitHub repo, create the Blueprint from `render.yaml`, and type the `sync: false` values in the dashboard (never in chat or Git).
6. **Owner:** create the Vercel project from the repo, root directory `apps/web`, and set the three `NEXT_PUBLIC_*` variables as build-time variables. Then put the resulting URL into Render's `CORS_ALLOWED_ORIGINS`.
7. **Smoke test** (see below), then record the observed results in `docs/IMPLEMENTATION_PLAN.md`.

## Smoke test (record what you observe, not what you expect)

- `GET <api>/healthz` → 200 and `GET <api>/readyz` → `ready` with the database `ok`.
- `GET <api>/v1/me` without a token → 401.
- Sign up on the web app (a confirmation email must arrive and its link must land signed in).
- Create a goal → generate a roadmap (a real Gemini plan, not labelled a sample) → open a lesson → take a quiz.
- Upload a small PDF → it reaches `ready` → a lesson cites it. (First real Storage run.)
- Download an export through a signed link.
- Second account sees none of the first account's data.
- Worker logs show `worker.started` and no secrets, tokens or learner text.

## Not covered yet

Migration-deploy job in CI, production project, custom domain, custom SMTP for auth email (the default sender is rate limited), Sentry, backups and a restore drill. These belong to M9.
