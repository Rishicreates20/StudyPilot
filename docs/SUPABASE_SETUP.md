# StudyPilot — Supabase setup

How to connect StudyPilot to a Supabase project: what to create, which settings to change, which values to copy and **where each one goes**. Follow Path A (a hosted project) for a first run; Path B (the local stack) needs Docker.

> Menu names were checked against Supabase's documentation on 2026-10-10. The dashboard changes often: if a label differs, search the dashboard for the setting's name in **bold**.

## 1. What you will configure

| Value | Where to get it | Secret? | Goes to |
|---|---|---|---|
| Project URL (`https://<ref>.supabase.co`) | **Connect** dialog, or Project Settings | No | Web: `NEXT_PUBLIC_SUPABASE_URL` · API: `SUPABASE_URL` |
| Publishable key (`sb_publishable_…`) | **Connect** dialog, or **Settings → API Keys** | No (public by design) | Web: `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` |
| Database connection string (**session pooler**) | **Connect → Session pooler**, plus the database password you chose | **Yes** | API only: `DATABASE_URL` |
| JWT signing mode | **Project Settings → JWT Signing Keys** | No | API: `SUPABASE_JWT_MODE` (`jwks` or `hs256`) |
| Legacy JWT secret | Same page, **only** for a legacy project | **Yes** | API only: `SUPABASE_JWT_SECRET` |
| Project ref (20 letters) | Project URL or Settings | No | CLI: `supabase link` |
| Database password | You chose it at project creation | **Yes** | CLI prompt, and inside `DATABASE_URL` |

**Never needed, never configured:** the secret key (`sb_secret_…`) and the legacy `service_role` key. They bypass Row Level Security. StudyPilot does not use them in this milestone; if you paste one into any file or variable you are doing something this guide did not ask for. (Server-side Storage and admin features arrive in a later milestone and will be documented then.)

## 2. Path A — a hosted Supabase project

### Step 1. Create the project

1. Create an account and a new project at supabase.com. Pick the region closest to your users, and **write down the database password** — Supabase will not show it again (you can reset it).
2. Note the project ref (the 20-letter part of `https://<ref>.supabase.co`).

### Step 2. Set the Auth options

In the dashboard's **Authentication** section:

| Setting | Value | Why |
|---|---|---|
| **Email** provider | Enabled | Sign-up and sign-in use email + password |
| **Confirm email** | **On** for anything real | The app handles both cases: with confirmation on, sign-up shows "check your email" and the link signs the user in |
| **Allow anonymous sign-ins** | **Off** | The API refuses anonymous tokens anyway; keep the project consistent |
| **Minimum password length** | 10 or more | The sign-up form requires 10 characters; a lower project minimum would still pass the form but be inconsistent |
| **Site URL** (URL Configuration) | Your web address, for example `https://app.example.com` (`http://localhost:3000` for a dev project) | Confirmation links are built from it |
| **Redirect URLs** | `https://app.example.com/auth/confirm` and `http://localhost:3000/auth/confirm` | The confirmation link lands on `/auth/confirm`; Supabase rejects unlisted redirect targets |

**Confirmation email template.** In **Authentication → Emails**, edit the *Confirm sign up* template so its link points at the app's confirm route. The template this repo uses locally is [`supabase/templates/confirmation.html`](../supabase/templates/confirmation.html); the important line is:

```html
<a href="{{ .SiteURL }}/auth/confirm?token_hash={{ .TokenHash }}&type=email">Confirm your email</a>
```

This is the server-side `token_hash` flow: the link is verified on the server and the session cookie is set there, so it works when the link is opened in a different browser tab. The app only accepts link types `email` and `signup`.

**Email delivery.** Supabase's built-in email sender is meant for trying things out: it is rate-limited and, on hosted projects, restricted to addresses of your own team. Configure custom SMTP (**Authentication → Emails → SMTP**) before inviting real users. Until then, either add yourself as a team member, or turn **Confirm email** off on a development project.

### Step 3. Keep the Data API away from the application tables

StudyPilot's browser never talks to Supabase tables; every data request goes through the FastAPI service (ADR-004). The tables are also protected in depth: Row Level Security is on, and the `anon` and `authenticated` roles hold only the grants the API needs. For defence in depth, turn the Data API off:

- Dashboard → **Integrations → Data API** (the Data API overview) → switch **Enable Data API** off.

Supabase confirms that with the Data API off none of its auto-generated REST endpoints respond, whatever the grants. If you prefer to leave it on, keep `public` out of the exposed schemas. Do not add the application tables to an exposed schema.

### Step 4. Apply the database migrations

The database schema lives only in [`supabase/migrations/`](../supabase/migrations/); there are no manual changes to make in the SQL editor.

```bash
npx supabase login
npx supabase link --project-ref <your-project-ref>
npx supabase db push --dry-run   # lists what would be applied
npx supabase db push
```

`link` asks for the database password. The two migrations create `profiles` (one row per user, filled automatically by a trigger when a user signs up) and `learning_goals`, each with Row Level Security and explicit grants. Check the result with `npx supabase migration list --linked`.

### Step 5. Choose the token verification mode

The API verifies every access token itself. Look at **Project Settings → JWT Signing Keys**:

| You see | Set in the API | Notes |
|---|---|---|
| An asymmetric key (ECC P-256 or RSA) as the **current** key | `SUPABASE_JWT_MODE=jwks` | Preferred. The API downloads the public keys from `https://<ref>.supabase.co/auth/v1/.well-known/jwks.json` (cached; Supabase's edge also caches it for about ten minutes). No secret is stored anywhere. |
| Only the legacy JWT secret | Either **migrate** (recommended), or `SUPABASE_JWT_MODE=hs256` with `SUPABASE_JWT_SECRET` | Click **Migrate JWT secret**, then rotate to the new asymmetric key; Supabase describes this as no-downtime. Supabase itself says a shared secret is "not recommended for production" because anyone who holds it can impersonate any user. |

If you start with `hs256` and later migrate, switch the API to `jwks` and redeploy. Tokens issued before the rotation are signed with the old secret and stop verifying in `jwks` mode; they expire within the access-token lifetime (one hour by default), and until then the affected users are sent to sign in again.

### Step 6. Copy the values into your environment

1. Open **Connect**. Copy the **project URL** and the **publishable key**.
2. In **Connect → Session pooler**, copy the connection string. Replace the password placeholder with your database password (percent-encode special characters, e.g. `@` → `%40`) and **append `?sslmode=require`**:

   ```text
   postgresql://postgres.<ref>:<password>@<pooler-host>:5432/postgres?sslmode=require
   ```

   Copy the host from the dialog rather than composing it: Supabase documents that the pooler host cannot be derived from your region. The API refuses to start in `staging` or `production` without `sslmode=require` (or `verify-*`).

   Why the **session** pooler: it is IPv4-reachable on every plan (the direct connection is IPv6-only unless you buy the IPv4 add-on) and it supports prepared statements. The transaction pooler (port 6543) also works with this API — it opens a transaction per request and sets the user's identity with transaction-local settings, and prepared statements are disabled in the connection pool — but there is no reason to prefer it for a long-lived server.
3. Create the two local files:

   ```text
   services/api/.env        # copy of services/api/.env.example
   apps/web/.env.local      # copy of apps/web/.env.example
   ```

   | File | Variable | Value |
   |---|---|---|
   | `services/api/.env` | `DATABASE_URL` | the pooler string above |
   | | `SUPABASE_URL` | the project URL |
   | | `SUPABASE_JWT_MODE` | `jwks` (or `hs256`, see Step 5) |
   | | `SUPABASE_JWT_SECRET` | only for `hs256` |
   | | `CORS_ALLOWED_ORIGINS` | `http://localhost:3000` locally; your `https://` web origin when deployed |
   | `apps/web/.env.local` | `NEXT_PUBLIC_SUPABASE_URL` | the project URL |
   | | `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` | the publishable key |
   | | `NEXT_PUBLIC_API_BASE_URL` | `http://localhost:8000` locally |

Both files are git-ignored. `.env.example` files contain placeholders only.

### Step 7. Run it

```bash
npm run dev:api     # http://localhost:8000   (Windows note: see docs/DEVELOPMENT.md)
npm run dev:web     # http://localhost:3000
```

Then check, in order:

1. `http://localhost:8000/readyz` → `{"status":"ready","checks":{"database":"ok"}}`. If the API exits at start with `DATABASE_URL and SUPABASE_URL must be set`, the `.env` file is missing or misnamed.
2. `http://localhost:8000/v1/me` in a browser → **401** `UNAUTHENTICATED`. This is correct: it proves the endpoint is protected.
3. In the web app: **Create account** → you land on **Your learning goals** (or on a "check your email" notice if confirmation is on) → **New goal** → the goal appears → **Sign out** → `/dashboard` sends you to sign-in → **Sign in** → your goal is still there.

### Deployed environments

| Where | What to set |
|---|---|
| **Vercel** (web) | `NEXT_PUBLIC_API_BASE_URL`, `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` as build-time variables (they are compiled into the bundle and are public by design). Optionally `API_INTERNAL_BASE_URL` for server-to-server calls. |
| **Render** (API) | `APP_ENV=production`, `DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_JWT_MODE`, `CORS_ALLOWED_ORIGINS` (https only), and `SUPABASE_JWT_SECRET` if `hs256`. Store `DATABASE_URL` and the JWT secret as secrets, not plain variables. |
| **GitHub Actions** | Nothing yet: CI starts its own throwaway Supabase stack. Secrets for deploying migrations (`SUPABASE_ACCESS_TOKEN`, database password) arrive with the deployment milestone. |

Add the deployed web address to Supabase's **Site URL** and **Redirect URLs** (Step 2), or confirmation links will point at the wrong place.

## 3. Path B — the local Supabase stack (needs Docker)

For work that should not touch a hosted project. This machine has no Docker, so this path is verified only in CI (see §5).

```bash
npx supabase start     # starts Postgres, Auth and the gateway; applies every migration
npx supabase status -o env
```

`status` prints the local URL (`http://127.0.0.1:54321`), a publishable key, the database URL (`postgresql://postgres:postgres@127.0.0.1:54322/postgres`) and the JWT secret. Use them like this:

| Variable | Local value |
|---|---|
| API `SUPABASE_URL` · web `NEXT_PUBLIC_SUPABASE_URL` | `http://127.0.0.1:54321` |
| web `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` | the publishable key from `status` (the older `ANON_KEY` also works) |
| API `DATABASE_URL` | the database URL from `status` |
| API `SUPABASE_JWT_MODE` / `SUPABASE_JWT_SECRET` | The CLI's `JWT_SECRET` with `hs256` for a stack that signs tokens with it. Check the algorithm of a token your stack issues (the `alg` in the JWT header, e.g. paste a token into jwt.io's header view locally): `HS256` → `hs256` mode; `ES256`/`RS256` → `jwks` mode. |

`.github/scripts/supabase_stack_env.py` automates exactly this decision for CI (it creates a throwaway account and reads the token header).

Locally, email confirmation is off (`supabase/config.toml`), so sign-up signs you in immediately; confirmation emails, if you turn them on, appear in the local Mailpit inbox (`http://127.0.0.1:54324`). To rebuild the database from the migrations: `npx supabase db reset`. Run the apps natively (`npm run dev:web`, `npm run dev:api`) against this stack; the Compose file is for a hosted project.

## 4. Environment variable reference

### API (`services/api/.env`)

| Variable | Required | Secret | Default | Meaning |
|---|---|---|---|---|
| `APP_ENV` | No | No | `local` | `local` · `test` · `staging` · `production`. Staging and production require https origins and `sslmode=require`; production turns off `/docs`. |
| `DATABASE_URL` | **Yes** (not in `test`) | **Yes** | — | Postgres connection string, see Step 6 |
| `SUPABASE_URL` | **Yes** (not in `test`) | No | — | Project URL; must be https in staging/production |
| `SUPABASE_JWT_MODE` | No | No | `jwks` | `jwks` or `hs256` |
| `SUPABASE_JWT_SECRET` | `hs256` only | **Yes** | — | At least 32 characters |
| `SUPABASE_JWT_AUDIENCE` | No | No | `authenticated` | Expected `aud` claim |
| `SUPABASE_JWT_ISSUER` | No | No | `{SUPABASE_URL}/auth/v1` | Expected `iss` claim |
| `SUPABASE_JWKS_URL` | No | No | `{SUPABASE_URL}/auth/v1/.well-known/jwks.json` | Where to fetch public keys |
| `JWT_LEEWAY_SECONDS` | No | No | `10` | Clock-skew tolerance, 0–60 |
| `DB_POOL_MIN_SIZE` / `DB_POOL_MAX_SIZE` / `DB_POOL_TIMEOUT_SECONDS` | No | No | `1` / `10` / `5` | Connection pool |
| `MAX_ACTIVE_GOALS_PER_USER` | No | No | `50` | Per-user cap; the 51st goal gets a 409 |
| `CORS_ALLOWED_ORIGINS` | No | No | `http://localhost:3000` | Web origins allowed to call the API from a browser |
| `LOG_LEVEL`, `APP_NAME`, `APP_VERSION` | No | No | `INFO`, `StudyPilot`, `0.1.0` | Logging and reporting |

### Web (`apps/web/.env.local`, or build variables on Vercel)

| Variable | Required | Secret | Meaning |
|---|---|---|---|
| `NEXT_PUBLIC_SUPABASE_URL` | Production builds; sign-in needs it | No | Project URL. Must be set together with the key. |
| `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` | Production builds; sign-in needs it | No (public) | Publishable (or legacy anon) key |
| `NEXT_PUBLIC_API_BASE_URL` | Production builds | No | Address of the API as the browser sees it |
| `API_INTERNAL_BASE_URL` | No | No | Address server-rendered pages use to reach the API (Docker: `http://api:8000`) |
| `NEXT_PUBLIC_APP_NAME` | No | No | Product name shown in the UI |

If Supabase is not configured in development, the sign-in and sign-up pages show a "Sign-in isn't set up yet" card naming the variables instead of failing. Production builds and servers refuse to start without them.

## 5. What is verified, and how

| Claim | Verified by | Observed |
|---|---|---|
| Token checks reject wrong signature, wrong algorithm (`none`, HS256-for-ES256), wrong audience/issuer, expired, anonymous, non-UUID subject | API unit tests with real signed tokens | Yes, locally |
| Ownership: another user's goal gives 404; list shows only your own; a request body naming another owner is refused | API tests against a real PostgreSQL 16 with the real migrations | Yes, locally |
| Row Level Security, grants, constraints, deleted accounts | Database tests against the same PostgreSQL | Yes, locally |
| Sign-in / sign-up / sign-out actions never echo passwords, never leak provider errors, refuse open redirects; the proxy refreshes the session and writes HttpOnly cookies; the API client sends only the bearer token | Web unit tests with the Supabase client mocked | Yes, locally |
| **Genuine Supabase Auth tokens verify; the profile trigger fires on a real `auth.users` insert; RLS holds under Supabase's own roles; PostgREST cannot read the tables; sign-out ends the session** | `services/api/tests/supabase_stack` against `supabase start` | **Only in CI** (needs Docker) — see the `supabase-stack` job |
| **Real browser flow: sign up, create a goal, reload, sign out, sign in, second user sees nothing** | Playwright (`apps/web/e2e`) against the same stack | **Only in CI** |

The two rows marked "only in CI" are the ones this machine cannot run. Do not treat them as proven until the `supabase-stack` job is green.

## 6. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| API exits immediately; log says `DATABASE_URL and SUPABASE_URL must be set` | Missing `services/api/.env` | Step 6. The message names variables, never values. |
| API exits with `DATABASE_URL must set sslmode=require` | `APP_ENV` is `staging`/`production` | Append `?sslmode=require` |
| `/readyz` reports the database as failing | Wrong password or host; IPv6-only direct connection from an IPv4 network | Use the **session pooler** string; check the password; percent-encode symbols |
| Every request to the API is 401 `INVALID_TOKEN` although you are signed in | Mode mismatch: `jwks` mode with a project that signs with the legacy secret, or the reverse | Step 5. The API log has a `reason` category (never the token). |
| You sign in successfully but keep landing on sign-in with "Your session has ended" | The API rejects tokens Supabase issues: signing mode mismatch (`jwks` vs `hs256`), a different `SUPABASE_URL` in the API than in the web app, or (for a deleted account) the account no longer exists | Compare `SUPABASE_URL` in both apps and re-check Step 5. The API log line `auth.rejected` carries a `reason` category, never the token. |
| 503 `AUTH_UNAVAILABLE` | The API could not fetch the JWKS and has no cached keys | Check `SUPABASE_URL` and network egress |
| 401 `ACCOUNT_NOT_FOUND` after sign-in | The user was deleted in Supabase (the token is still valid until it expires) | Sign in again with a different account; deleting a user also deletes their goals |
| "Sign-in isn't set up yet" card in the web app | `NEXT_PUBLIC_SUPABASE_*` unset | Step 6, then restart the dev server (these are read at start/build time) |
| Confirmation link lands on sign-in with "invalid or expired" | Link used twice or older than its lifetime, or the template points elsewhere | Sign up again; check the template (Step 2) |
| Sign-up works but no email arrives | Built-in sender limits | Use custom SMTP, or turn **Confirm email** off on a dev project |
| `os error 4551` / "Application Control policy has blocked this file" on Windows | Smart App Control refused an unsigned launcher | See `docs/DEVELOPMENT.md` (Windows notes). Do not turn the setting off. |

## 7. Security reminders

- The repository is public. Never commit `.env`, a connection string, a JWT secret or any key other than the publishable key. CI runs a secret scan.
- If a database password or JWT secret is ever exposed: reset the database password (Project Settings → Database), and for a legacy project migrate to signing keys and revoke the old secret. Supabase's API-keys guide describes rotation.
- The API trusts only the verified token. User IDs sent by the browser are ignored; a body that names an owner is rejected with a 422.
- Sessions are HttpOnly cookies, written by the server. The web app never uses Supabase's browser client, so no token is readable by page scripts.
