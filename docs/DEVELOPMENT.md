# Local development

Everything below was run on the primary development machine (Windows 11, Git Bash). Commands that
could not be run there are marked **not verified locally**.

## Prerequisites

| Tool | Version | Notes |
|---|---|---|
| Git | any recent | The repo normalises line endings to LF (`.gitattributes`) |
| Node.js + npm | Node 24, npm 11 | `.nvmrc` pins 24. The repo uses **npm workspaces** (no pnpm) |
| [uv](https://docs.astral.sh/uv/) | 0.12 | Installs and manages Python for the API |
| Python | 3.14 | `uv` fetches it automatically; pinned in `services/api/.python-version` |
| Docker | optional | Only for the Compose stack |

Not needed yet: a Supabase project, LLM keys. Those arrive with later milestones
([IMPLEMENTATION_PLAN §6](IMPLEMENTATION_PLAN.md#6-external-services-accounts-and-credentials)).

## Install

```bash
git clone https://github.com/Rishicreates20/StudyPilot.git
cd StudyPilot

npm install                         # web dependencies (workspaces)
uv sync --directory services/api    # API dependencies into services/api/.venv
```

Optional configuration (both apps run with defaults, so you can skip this):

```bash
cp services/api/.env.example services/api/.env
cp apps/web/.env.example     apps/web/.env.local
```

## Run

Two terminals:

```bash
npm run dev:api     # FastAPI on http://localhost:8000   (interactive docs: /docs)
npm run dev:web     # Next.js on http://localhost:3000
```

Then open:

| URL | What it is |
|---|---|
| <http://localhost:3000> | Landing page |
| <http://localhost:3000/status> | Live health of the web app and the API (the API must be running) |
| <http://localhost:3000/design> | The design system preview (sample content) |
| <http://localhost:3000/api/health> | Web liveness probe (JSON) |
| <http://localhost:8000/healthz> | API liveness probe |
| <http://localhost:8000/readyz> | API readiness probe (200 ready / 503 when a dependency check fails) |
| <http://localhost:8000/docs> | OpenAPI docs (disabled when `APP_ENV=production`) |

## Check everything

```bash
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
| `npm run build` | Production build of the web app (needs `NEXT_PUBLIC_API_BASE_URL`) |

Watch mode for web tests: `npm run test:watch --workspace @studypilot/web`.

## Docker (not verified locally)

The dev machine has no Docker, so these files are validated for YAML syntax only. The CI `docker`
job builds every image target and boots the runtime images, checking all four health endpoints.

```bash
docker compose up --build     # API :8000 and web :3000, both with hot reload
docker compose down
```

The production images can be built individually:

```bash
docker build --target runtime -t studypilot-api services/api
docker build -f apps/web/Dockerfile --target runtime \
  --build-arg NEXT_PUBLIC_API_BASE_URL=https://api.example.com -t studypilot-web .
```

## Configuration reference

All configuration is environment variables, validated at startup. A bad value stops the process
(exit code 78) with a message naming the variable, never the value.

### API (`services/api/.env`)

| Variable | Default | Notes |
|---|---|---|
| `APP_ENV` | `local` | `local`, `test`, `staging`, `production`. Production disables `/docs` and uses JSON logs |
| `APP_NAME` | `StudyPilot` | Reported by `/healthz` |
| `APP_VERSION` | `0.1.0` | Reported by `/healthz` |
| `LOG_LEVEL` | `INFO` | `DEBUG` … `CRITICAL` |
| `CORS_ALLOWED_ORIGINS` | `http://localhost:3000` | Comma-separated origins, no path. Must be `https` in staging/production |

### Web (`apps/web/.env.local`)

| Variable | Default | Notes |
|---|---|---|
| `NEXT_PUBLIC_APP_NAME` | `StudyPilot` | Public. Shown in the UI |
| `NEXT_PUBLIC_API_BASE_URL` | `http://localhost:8000` in development; **required in production builds** | Public (compiled into the browser bundle). Never put secrets in `NEXT_PUBLIC_*` |
| `API_INTERNAL_BASE_URL` | the public URL | Server-only. Set when server-rendered pages reach the API by a different address (Docker: `http://api:8000`) |

`NEXT_PUBLIC_*` values are inlined at **build** time, so changing them requires a rebuild (in Docker,
pass them as `--build-arg`).

## Troubleshooting

**`An Application Control policy has blocked this file` (Windows).** Smart App Control blocks unsigned
native code. Verified here: Python 3.14 via `uv` works; Python 3.12 does not (`ssl` blocked). The
`pytest.exe` launcher that `uv` generates is blocked, which is why every API script uses
`python -m pytest` / `-m ruff` / `-m pyright`. Do not disable Smart App Control as a workaround;
run the failing tool as `uv run python -m <tool>` or use CI.

**Installs are slow or fail with path errors (Windows).** Long paths are off by default, so keep the
checkout path short. Cloud-synced folders (OneDrive) can slow `npm install` considerably and lock
files; prefer a folder outside sync, such as `C:\dev\StudyPilot`.

**`npm install` warns about install scripts.** npm 11 reports packages with lifecycle scripts that are
not yet approved. The only one today is `unrs-resolver`, which is not needed for this project; leave
it unapproved.

**`npm audit` reports high-severity issues.** Production dependencies are clean
(`npm audit --omit=dev` finds 0). The dev-only findings come from `braces` (a stack-exhaustion issue
in glob matching) inside `eslint-config-next`; npm's suggested "fix" downgrades Next.js to 14 and
must not be applied. CI audits production dependencies only.

**Web `Invalid environment configuration` on start.** Read the variable names it lists and compare
with the table above.

**`/status` shows the API as unreachable.** Start it (`npm run dev:api`) and click *Re-check*. Inside
Docker the web container must have `API_INTERNAL_BASE_URL=http://api:8000`.

**Port already in use.** API `8000`, web `3000`. Stop the other process or change `--port`
(and `NEXT_PUBLIC_API_BASE_URL` / `CORS_ALLOWED_ORIGINS` to match).
