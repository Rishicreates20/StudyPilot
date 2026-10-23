# Deployment guide (proposed, nothing here has been deployed)

Status on 2026-10-23: **no deployment of the API or worker exists.** The web app's Vercel project
exists but its build fails (see §1). `render.yaml` is a proposal for the API and worker; it has been
checked for valid YAML and against the API's own production settings validation, but **Render has
never read it**. Do not describe any of this as deployed until a deployment has been observed.

What only the owner can do: create the Render account (it needs a payment method), enter the
secrets, and set the Vercel variables. Nobody else should be given the database password.

## 1. Fix the web build on Vercel first

Vercel has failed on every recent `main` commit. The web app refuses to build without its public
variables (reproduced locally: `NEXT_PUBLIC_API_BASE_URL: is required`). The Vercel build log was
not readable from here, so the cause is **likely, not confirmed**.

In the Vercel project: Settings → General → **Root Directory = `apps/web`**; Settings → Environment
Variables:

| Variable | Value |
|---|---|
| `NEXT_PUBLIC_SUPABASE_URL` | `https://<project-ref>.supabase.co` |
| `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` | the project's publishable key (`sb_publishable_…`) |
| `NEXT_PUBLIC_API_BASE_URL` | the API's public https address from Render (§3), no trailing slash |

`NEXT_PUBLIC_API_BASE_URL` is only known after the API exists, so do §2 and §3 first, then set it
and redeploy.

## 2. Supabase prerequisites (the hosted project)

- Migrations: the hosted StudyPilot project has all ten migrations through `exports`; the repository
  now has the same ten files (the last two were recovered, see `docs/IMPLEMENTATION_PLAN.md`
  under M7 and M8). There is **no migration deploy job**: later migrations are applied by hand.
- The `vector` extension is created by the documents migration (already applied there).
- Storage: the `documents` bucket and its policies are created by the documents migration where
  Storage exists. **They have never been exercised with a real file.** Test one upload before
  trusting it.
- Authentication → Password security: **leaked-password protection is off** (Supabase advisor
  warning). Turn it on in the dashboard.
- Authentication → URL configuration: add the web app's https address as the Site URL and a
  redirect URL, or sign-up confirmation links will point to the wrong place.

## 3. Render (API and worker)

1. Push `render.yaml` to `main` (this file is in the repository root).
2. Render dashboard → New → **Blueprint** → choose the repository. Render reads `render.yaml` and
   shows two services: `studypilot-api` (web) and `studypilot-worker` (background worker).
3. It then asks for each `sync: false` value, **once**, for **each** service (Render does not allow
   secrets in shared groups, so enter the same values twice):

   | Variable | What to enter |
   |---|---|
   | `DATABASE_URL` | Supabase Dashboard → Connect → **Session pooler** string, ending `?sslmode=require`. A secret: it holds the database password. |
   | `SUPABASE_URL` | `https://<project-ref>.supabase.co` |
   | `SUPABASE_PUBLISHABLE_KEY` | the publishable key (public by design) |
   | `GEMINI_API_KEY` | a Gemini API key. A secret. |
   | `CORS_ALLOWED_ORIGINS` | the web app's https address, e.g. `https://studypilot.vercel.app` (no path, no trailing slash) |

4. Wait for the API to deploy, then open `https://<service>.onrender.com/healthz` (should answer
   200) and `/readyz` (200 only if the database is reachable).
5. Copy the API's address into Vercel as `NEXT_PUBLIC_API_BASE_URL` (§1) and redeploy the web app.

Choices made in `render.yaml`, and why:

- **Region `singapore`**, the same as the Supabase project; it cannot be changed after creation.
- **`autoDeployTrigger: checksPass`**: Render deploys a commit only after the repository's CI checks
  pass on it.
- **`PORT=8000`**: the image listens on 8000.
- **`/healthz` for the health check**, not `/readyz`, so a database blip does not restart the API.
- **Small connection pools** (6 for the API, 4 for the worker): Supabase's session pooler allows few
  connections.
- **`APP_ENV=production`**: turns off the interactive API docs and makes the API refuse
  `LLM_PROVIDER=fake`, local file storage, non-https origins and a database URL without `sslmode`.
- **Plans:** the web service is set to `starter`; the worker has no `plan`, so Render's default
  worker size applies. Free instances are not available for workers, and a free web service
  sleeps when idle, which would stall the job queue's API. **Check current pricing** before
  applying; the plan names were read from Render's docs on 2026-10-23.

## 4. What is not verified

- Render has never built this image or read this file. CI builds and boots the API image on every
  push (the `Docker` job), which is the only evidence it builds.
- The worker's command (`python -m app.worker`) is the one the local scripts use; it has not been
  run inside this image on Render.
- The Gemini free tier allows about 20 requests per model per day; real use will hit quota errors
  (`AI_QUOTA_EXHAUSTED`) quickly. A paid key is needed for more than a handful of learners.
- Supabase Storage with real files, and a whole document taken through the deployed app, are
  unobserved.
- Cost is not estimated here.

## 5. Order, in one list

1. Turn on leaked-password protection; add the Site/redirect URLs in Supabase (after the web
   address is known).
2. Create the Render Blueprint; enter the secrets; confirm `/healthz` and `/readyz`.
3. Set the three `NEXT_PUBLIC_*` variables and the Root Directory in Vercel; redeploy; confirm the
   build passes.
4. Sign up with a test account, create a goal, generate a roadmap with the real provider, upload one
   small document. Report what actually happened.
