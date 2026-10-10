# Local development

Everything below was run on the primary development machine (Windows 11, Git Bash) unless it is
marked **not verified locally**. That machine has no Docker, so anything that needs a real Supabase
stack (genuine Supabase Auth tokens, the browser flow) is verified only in CI.

## Prerequisites

| Tool | Version | Notes |
|---|---|---|
| Git | any recent | The repo normalises line endings to LF (`.gitattributes`) |
| Node.js + npm | Node 24, npm 11 | `.nvmrc` pins 24. The repo uses **npm workspaces** (no pnpm) |
| [uv](https://docs.astral.sh/uv/) | 0.12 | Installs and manages Python for the API |
| Python | 3.14 | `uv` fetches it automatically; pinned in `services/api/.python-version` |
| Python 3.12 | any 3.12 | Only for the API tests' throwaway PostgreSQL; `uv` fetches it too (see "Test the API") |
| A Supabase project | free tier is fine | Needed to *use* the app; see [SUPABASE_SETUP.md](SUPABASE_SETUP.md). Not needed to run the tests |
| Docker | optional | The Compose stack, or the local Supabase stack (`npx supabase start`) |

LLM keys are not needed yet; they arrive with the AI milestones
([IMPLEMENTATION_PLAN §6](IMPLEMENTATION_PLAN.md#6-external-services-accounts-and-credentials)).

## Install

```bash
git clone https://github.com/Rishicreates20/StudyPilot.git
cd StudyPilot

npm install                         # web dependencies (workspaces)
uv sync --directory services/api    # API dependencies into services/api/.venv
```

## Configure

The API needs your Supabase project's values and refuses to start without them. The web app starts
without them but cannot sign anyone in. [SUPABASE_SETUP.md](SUPABASE_SETUP.md) explains where each
value comes from.

```bash
cp services/api/.env.example services/api/.env        # then fill in DATABASE_URL, SUPABASE_URL, …
cp apps/web/.env.example     apps/web/.env.local      # then fill in NEXT_PUBLIC_SUPABASE_*
```

## Run

Two terminals:

```bash
npm run dev:api     # FastAPI on http://localhost:8000   (interactive docs: /docs)
npm run dev:web     # Next.js on http://localhost:3000
```

`dev:api` passes `--loop asyncio:SelectorEventLoop`. The database driver (psycopg) cannot use the
Windows default event loop; on Linux and macOS the flag changes nothing.

| URL | What it is |
|---|---|
| <http://localhost:3000> | Landing page |
| <http://localhost:3000/sign-up> · `/sign-in` | Create an account · sign in |
| <http://localhost:3000/dashboard> | Your goals (redirects to sign-in when signed out) |
| <http://localhost:3000/goals/new> | Create a goal |
| <http://localhost:3000/status> | Live health of the web app and the API (the API must be running) |
| <http://localhost:3000/design> | The design system preview (sample content) |
| <http://localhost:3000/api/health> | Web liveness probe (JSON) |
| <http://localhost:8000/healthz> | API liveness probe |
| <http://localhost:8000/readyz> | API readiness probe (200 ready / 503 when the database check fails) |
| <http://localhost:8000/docs> | OpenAPI docs (disabled when `APP_ENV=production`) |

## Check everything

```bash
uv sync --directory services/api/tests/pg_server   # one-off: installs the test database
npm run check
```

That runs, in order: formatting check (Prettier + `ruff format`), lint (ESLint + `ruff check`),
type-check (`next typegen && tsc` + `pyright` strict), and tests (Vitest + pytest).
Individual commands:

| Command | Does |
|---|---|
| `npm run format` / `format:check` | Write / verify formatting for both apps |
| `npm run lint[:web\|:api]` | ESLint / ruff |
| `npm run typecheck[:web\|:api]` | `tsc` / pyright |
| `npm run test[:web\|:api]` | Vitest / pytest |
| `npm run contracts:generate` | Rewrite `packages/contracts` from the API's OpenAPI document |
| `npm run contracts:check` | Same, then fail if anything changed (CI runs this) |
| `npm run build` | Production web build (needs the three `NEXT_PUBLIC_*` variables below) |

Watch mode for web tests: `npm run test:watch --workspace @studypilot/web`.

A production build needs the public variables, for example:

```bash
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000 \
NEXT_PUBLIC_SUPABASE_URL=https://<ref>.supabase.co \
NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=<publishable key> npm run build
```

### Test the API

`npm run test:api` starts a **real PostgreSQL 16** (the `pgserver` wheel, run by a small helper in
`services/api/tests/pg_server` on Python 3.12, because the wheel has no 3.14 build), applies a stand-in
for Supabase's roles and `auth` schema plus every file in `supabase/migrations`, and runs the suite
against it. Tokens are real JWTs signed with keys the tests generate; nothing is faked by flipping a
flag. The first run needs `uv sync --directory services/api/tests/pg_server`.

To use your own empty PostgreSQL instead (CI does): set `TEST_DATABASE_URL=postgresql://…`.

The tests under `services/api/tests/supabase_stack` need a **genuine Supabase stack** and skip
themselves otherwise. To run them where Docker is available:

```bash
npx supabase start -x realtime,storage-api,imgproxy,mailpit,postgres-meta,studio,edge-runtime,logflare,vector,supavisor
python .github/scripts/supabase_stack_env.py            # prints the variable names it would export
# export the SUPABASE_STACK_* variables it lists, then:
uv run --directory services/api python -m pytest tests/supabase_stack -v
```

### Browser tests (Playwright)

`apps/web/e2e` drives a real browser through sign-up, goal creation, reload, sign-out, sign-in and a
second user who must see none of it. It needs the same stack, a production build made with the
stack's `NEXT_PUBLIC_*` values, and a browser: see the header of `apps/web/playwright.config.ts`, then

```bash
cd apps/web
npx playwright install chromium
npm run build && npm run e2e
```

Neither of these two suites could be run on the primary machine (no Docker); the `supabase-stack` job
in CI runs both.

## Docker (not verified locally)

The dev machine has no Docker, so these files are validated for YAML syntax only. The CI `docker`
job builds every image target and boots the runtime images, checking all four health endpoints.

```bash
docker compose up --build     # API :8000 and web :3000, both with hot reload
docker compose down
```

Compose reads `DATABASE_URL`, `SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_*` and the JWT settings from your
shell or a root `.env` (copy `.env.example`). Use a hosted Supabase project with Compose: a local
Supabase stack listens on the host's `localhost`, which containers cannot reach, so run the apps
natively against that stack instead.

The production images can be built individually:

```bash
docker build --target runtime -t studypilot-api services/api
docker build -f apps/web/Dockerfile --target runtime \
  --build-arg NEXT_PUBLIC_API_BASE_URL=https://api.example.com \
  --build-arg NEXT_PUBLIC_SUPABASE_URL=https://<ref>.supabase.co \
  --build-arg NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=<publishable key> -t studypilot-web .
```

## Configuration reference

All configuration is environment variables, validated at startup. A bad value stops the process
(exit code 78) with a message naming the variable, never the value. The complete tables, with
defaults and which values are secret, are in [SUPABASE_SETUP.md §4](SUPABASE_SETUP.md#4-environment-variable-reference).
In short:

- **API (`services/api/.env`)** — required: `DATABASE_URL` (secret), `SUPABASE_URL`. Also
  `SUPABASE_JWT_MODE` (`jwks` or `hs256`) and, for `hs256`, `SUPABASE_JWT_SECRET` (secret);
  `CORS_ALLOWED_ORIGINS`, `APP_ENV`, `LOG_LEVEL`, pool and limit settings are optional.
- **Web (`apps/web/.env.local`)** — `NEXT_PUBLIC_SUPABASE_URL` and `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`
  (both public), `NEXT_PUBLIC_API_BASE_URL` (required in production builds), optional
  `API_INTERNAL_BASE_URL` and `NEXT_PUBLIC_APP_NAME`.

`NEXT_PUBLIC_*` values are inlined at **build** time, so changing them requires a rebuild (in Docker,
pass them as `--build-arg`). The Supabase service-role / secret key is never configured anywhere.

## Troubleshooting

**`An Application Control policy has blocked this file` / `os error 4551` (Windows).** Smart App
Control blocks unsigned native code it has no reputation for, and its verdicts can change between
days. Seen here: Python 3.12's `ssl`; the `pytest.exe`-style launchers `uv` generates (hence every
API script uses `python -m pytest` / `-m ruff` / `-m pyright`); and, on 2026-10-10, the virtual
environment's own `.venv\Scripts\python.exe` launcher and `ruff.exe`, which had worked the day
before (recreating the venv did not help). Do not disable Smart App Control. What still works is
the real interpreter itself, pointed at the venv's packages:

```bash
PY="$HOME/AppData/Roaming/uv/python/cpython-3.14-windows-x86_64-none/python.exe"
cd services/api
export PYTHONPATH="$(pwd -W)/.venv/Lib/site-packages;$(pwd -W)"
"$PY" -m pytest            # also: -m pyright
```

`ruff` cannot run that way (it is a native executable); use CI for lint and format checks while that
block lasts. Node tools (ESLint, Prettier, `tsc`, Vitest) are unaffected.

**Installs are slow or fail with path errors (Windows).** Long paths are off by default, so keep the
checkout path short. Cloud-synced folders (OneDrive) can slow `npm install` considerably and lock
files; prefer a folder outside sync, such as `C:\dev\StudyPilot`.

**`npm install` warns about install scripts.** npm 11 reports packages with lifecycle scripts that are
not yet approved. The only one today is `unrs-resolver`, which is not needed for this project; leave
it unapproved.

**`npm audit` reports high-severity issues.** Production dependencies are clean
(`npm audit --omit=dev` finds 0). The dev-only findings come from `braces` (a stack-exhaustion issue
in glob matching, only reachable through build-time tooling: `eslint-config-next` and the shadcn CLI);
npm's suggested "fix" downgrades Next.js to 14 or shadcn to 1.0 and must not be applied. CI audits
production dependencies only (`npm audit --omit=dev --audit-level=high`), so the `shadcn` package
must stay in `devDependencies`: `shadcn init` adds it under `dependencies`, which pulls the vulnerable
glob chain into the production tree.

**API exits at start with `DATABASE_URL and SUPABASE_URL must be set`.** Create `services/api/.env`
([SUPABASE_SETUP.md](SUPABASE_SETUP.md)). Other configuration errors name the variable the same way.

**API tests fail with `The test database is not installed`.** Run
`uv sync --directory services/api/tests/pg_server` once.

**Web `Invalid environment configuration` on start.** Read the variable names it lists and compare
with the tables above. Production builds need all three `NEXT_PUBLIC_*` values.

**The sign-in page says "Sign-in isn't set up yet".** `NEXT_PUBLIC_SUPABASE_URL` and
`NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` are unset; set them and restart `npm run dev:web`.

**`/status` shows the API as unreachable.** Start it (`npm run dev:api`) and click *Re-check*. Inside
Docker the web container must have `API_INTERNAL_BASE_URL=http://api:8000`.

**Port already in use.** API `8000`, web `3000`. Stop the other process or change `--port`
(and `NEXT_PUBLIC_API_BASE_URL` / `CORS_ALLOWED_ORIGINS` to match).
