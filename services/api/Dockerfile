# syntax=docker/dockerfile:1
#
# API image. Build context is services/api:
#   docker build -t studypilot-api services/api              (runtime image)
#   docker build -t studypilot-api:dev --target dev services/api
#
# One image serves both the API and (later) the worker; only the command differs.

FROM python:3.14-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv
RUN pip install --no-cache-dir uv==0.12.15
WORKDIR /srv/api

# --- Production dependencies only ----------------------------------------------------------
FROM base AS deps
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev

# --- Development image: includes test/lint tools; source is bind-mounted by Compose ----------
FROM base AS dev
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen
ENV PATH="/opt/venv/bin:$PATH"
COPY . .
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--reload", "--reload-dir", "app"]

# --- Runtime image ---------------------------------------------------------------------------
FROM python:3.14-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"
RUN groupadd --system --gid 10001 app && useradd --system --uid 10001 --gid app --no-create-home app
WORKDIR /srv/api
COPY --from=deps /opt/venv /opt/venv
COPY app ./app
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2).status == 200 else 1)"]
CMD ["python", "-m", "uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
