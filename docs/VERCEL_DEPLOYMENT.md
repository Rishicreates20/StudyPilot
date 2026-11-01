# Deploying StudyPilot on Vercel

Status on 2026-11-01: **not deployed yet.** The repository is ready (`vercel.json`, the API entrypoint
and the Vercel Queues worker, ADR-052), and every local check passes, but nothing in this guide
has run on Vercel. The Vercel connector has not been granted access to the team yet, so the
project's settings, environment variables and build logs could not be read or changed. Do not
describe the app as deployed until a deployment has been opened and checked.

## 1. What runs where

| Part | Where | How |
|---|---|---|
| Web app (Next.js 16, `apps/web`) | Vercel, service `web` | The only public part. Every path is rewritten to it. |
| API (FastAPI, `services/api`) | Vercel, service `api`, Python 3.14 function (`app.asgi:app`) | Private: no public route. The web app's server code reaches it through a service binding that Vercel injects as `API_INTERNAL_BASE_URL` at runtime. A Preview deployment talks to its own API. |
| Worker (AI generation, documents, marking) | Vercel Queues + a private queue-triggered function (`app.jobs.queue_consumer`) | Each request that queues a job publishes an empty wake-up message. The function runs jobs for up to about two minutes and asks for another run if work is left (ADR-052). |
| Database, sign-in, files | The existing Supabase project (`StudyPilot`, Singapore) | Unchanged. Functions run in `sin1` (Singapore) to sit next to it. |

Why not the long-running worker: on the Hobby plan a function stops after 300 seconds, cron jobs
run at most once a day, and an always-on Daemon uses up Hobby's monthly memory quota in about 17
days. Elsewhere (local, Docker) `python -m app.worker` still works exactly as before
(`JOB_WAKE=none`, the default).

## 2. Limits to know about

- **Uploads are capped at about 4 MB on Vercel** (4.5 MB is the request limit of a Vercel Function).
  Set `DOCUMENT_MAX_BYTES=4000000`; the upload form reads the limit from the API.
- **A job must finish within about 5 minutes** of the run that starts it. A run starts new jobs only
  during its first `JOB_DRAIN_SECONDS` (120 by default). A job cut off at the limit is picked up
  again by the next run and resumes from its last checkpoint, up to `JOB_MAX_ATTEMPTS` (3). A very
  large document read by OCR could exceed this. That hasn't been measured.
- **Preview and Production share the one Supabase database.** A Preview writes real rows. There is
  no staging database yet.
- Services, Queues for Python and the Python subscriber configuration are **beta** features.

## 3. One-time setup (owner)

These steps need the account owner. Secrets are typed into the dashboards, never into chat or Git.

1. **Let the Vercel connector manage the project** (if an assistant does the rest): approve the
   team-access link it shows you.
2. **Vercel project `studypilot` → Settings → General:** Root Directory **empty** (the repository
   root, where `vercel.json` is). Framework preset: let `vercel.json` decide. Node.js 24.
3. **Environment variables** (Settings → Environment Variables), for **Production and Preview**:

   | Name | Value | Secret? |
   |---|---|---|
   | `NEXT_PUBLIC_SUPABASE_URL` | `https://<project-ref>.supabase.co` | no |
   | `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` | the publishable key (`sb_publishable_…`) | no (public by design) |
   | `APP_ENV` | `production` | no |
   | `SUPABASE_URL` | `https://<project-ref>.supabase.co` | no |
   | `SUPABASE_PUBLISHABLE_KEY` | the same publishable key | no |
   | `SUPABASE_JWT_MODE` | `jwks` | no |
   | `DATABASE_URL` | Supabase → Connect → **Session pooler** string, ending `?sslmode=require` | **yes** |
   | `LLM_PROVIDER` | `gemini` | no |
   | `GEMINI_API_KEY` | a Gemini API key | **yes** |
   | `GEMINI_FALLBACK_MODELS` | optional, comma-separated models to try when the default is busy | no |
   | `DOCUMENT_STORAGE` | `supabase` | no |
   | `DOCUMENT_MAX_BYTES` | `4000000` | no |
   | `JOB_WAKE` | `vercel_queue` | no |
   | `CORS_ALLOWED_ORIGINS` | the production address, e.g. `https://studypilot.vercel.app` | no |
   | `DB_POOL_MAX_SIZE` | `4` (each function instance opens its own pool) | no |

   Never set the Supabase service-role key, and never put a secret in a `NEXT_PUBLIC_` variable.
   `API_INTERNAL_BASE_URL` is set by the service binding: do not add it.
4. **Supabase → Authentication → URL Configuration:** set the Site URL to the production address and
   add it (and `https://*-<team>.vercel.app` for Previews, if wanted) to the redirect URLs, so
   sign-up confirmation links come back to `/auth/confirm` on Vercel.
5. **Supabase → Authentication → Password security:** turn on leaked-password protection (an
   advisor warning today).
6. **Database migrations:** the hosted project has every migration up to `exports`. Apply
   `20261023100000_flashcards.sql` (and any later one) before deploying code that uses it. There is
   no migration job: apply them in order in the SQL editor or through the Supabase connector.

## 4. Deploying

The Git integration builds every push:

- A **Preview** for every branch and pull request. Its queue messages stay within that deployment.
- **Production** for `main`.

Before trusting a deployment:

1. Open the deployment's build logs: both services (`web`, `api`) must build, and the build must list
   the generated queue subscriber.
2. Open `/status` on the deployment: it reports whether the web app can reach the API, and the API's
   database check.
3. Sign up with a test address, create a goal, start a roadmap, and watch the job move from queued
   to finished. The function logs show `jobs.woken` (the API) and `worker.drained` (the run).

## 5. Troubleshooting

| Symptom | Likely cause |
|---|---|
| Build fails with `EnvValidationError` in the web service | `NEXT_PUBLIC_SUPABASE_URL` or `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` is missing for that environment. |
| `/status` says the API is unreachable | The binding is missing (check `vercel.json`) or the API failed to start: read the `api` function logs (a settings error names the variable, never its value). |
| Jobs stay queued | `JOB_WAKE` is not `vercel_queue`, or the subscriber was not generated (build log), or `jobs.wake_failed` appears in the API logs. Queuing any new job wakes the worker again. |
| A job fails with `WORKER_LOST` | It was cut off at the time limit three times. Check how long it runs, and lower `JOB_DRAIN_SECONDS` or split the work. |
| Uploads fail with 413 | The file is above the 4.5 MB request limit: lower `DOCUMENT_MAX_BYTES`. |

## 6. Rolling back

Vercel → Deployments → choose the last good Production deployment → **Instant Rollback**. Queue
messages stay with the deployment that published them, so the rolled-back deployment keeps
processing its own until they are acknowledged or expire. Delete a bad deployment to stop its
consumers at once. Database migrations are not rolled back by this: they are written to be
additive.

## 7. Still to do before real users

The rest of this list is in `docs/IMPLEMENTATION_PLAN.md` (M9):

- A first observed deployment and a person walking through the main flows.
- Real Supabase Storage with real files.
- A staging database separate from production.
- Custom SMTP for sign-up emails.
- Monitoring and alerts.
- Privacy policy and terms.
