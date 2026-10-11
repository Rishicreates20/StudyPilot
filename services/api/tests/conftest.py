import asyncio
from collections.abc import AsyncIterator, Callable, Iterator
from dataclasses import dataclass
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.core.config import AppEnv, LlmProviderName, Settings
from app.core.db import Database
from app.main import create_app
from support.database import create_auth_user, running_database
from support.keys import SigningKey, build_claims, make_ec_key, sign_with_key, static_jwks_fetcher
from support.settings import TEST_SUPABASE_URL, IsolatedSettings
from support.worker import clear_queue, worker_settings

_CONFIG_VARIABLES = (
    "APP_ENV",
    "APP_NAME",
    "APP_VERSION",
    "LOG_LEVEL",
    "CORS_ALLOWED_ORIGINS",
    "DATABASE_URL",
    "DB_POOL_MIN_SIZE",
    "DB_POOL_MAX_SIZE",
    "DB_POOL_TIMEOUT_SECONDS",
    "SUPABASE_URL",
    "SUPABASE_JWT_MODE",
    "SUPABASE_JWT_SECRET",
    "SUPABASE_JWT_AUDIENCE",
    "SUPABASE_JWT_ISSUER",
    "SUPABASE_JWKS_URL",
    "JWT_LEEWAY_SECONDS",
    "MAX_ACTIVE_GOALS_PER_USER",
    "ROADMAP_JOBS_PER_USER_PER_DAY",
    "LESSON_JOBS_PER_USER_PER_DAY",
    "LESSON_JOBS_ACTIVE_PER_USER",
    "QUIZ_JOBS_PER_USER_PER_DAY",
    "QUIZ_QUESTION_COUNT",
    "QUIZ_SHORT_ANSWERS",
    "MASTERY_NEEDS_PRACTICE_BELOW",
    "MASTERY_MASTERED_FROM",
    "MASTERY_RECENCY_DECAY",
    "MASTERY_MIN_ANSWERS",
    "LLM_PROVIDER",
    "GEMINI_API_KEY",
    "GEMINI_MODEL",
    "GEMINI_BASE_URL",
    "LLM_TIMEOUT_SECONDS",
    "LLM_MAX_OUTPUT_TOKENS",
    "LLM_TEMPERATURE",
    "JOB_MAX_ATTEMPTS",
    "JOB_LEASE_SECONDS",
    "JOB_RETRY_BASE_SECONDS",
    "WORKER_POLL_SECONDS",
    "WORKER_CONCURRENCY",
)


@pytest.fixture(autouse=True)
def _isolated_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests must not depend on the developer's shell environment."""
    for name in _CONFIG_VARIABLES:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(scope="module")
def anyio_backend() -> tuple[str, dict[str, object]]:
    """Run async tests on a selector loop: psycopg's async mode rejects Windows' proactor loop."""
    return ("asyncio", {"loop_factory": asyncio.SelectorEventLoop})


def new_client(app: FastAPI) -> TestClient:
    # psycopg's async mode needs a selector event loop; Windows defaults to the proactor loop.
    return TestClient(
        app,
        raise_server_exceptions=False,
        backend_options={"loop_factory": asyncio.SelectorEventLoop},
    )


# --- Without a database: health, settings, error handling ---------------------------------------


@pytest.fixture
def settings() -> Settings:
    return IsolatedSettings(app_env=AppEnv.TEST)


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    return create_app(settings)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    # raise_server_exceptions=False: exercise the real 500 handler instead of re-raising.
    with new_client(app) as test_client:
        yield test_client


# --- With a real (PGlite) database and real signed tokens ---------------------------------------


@pytest.fixture(scope="session")
def database_dsn() -> Iterator[str]:
    """A PostgreSQL with the Supabase stub and every migration applied (one per test session)."""
    with running_database() as dsn:
        yield dsn


@pytest.fixture(scope="session")
def signing_key() -> SigningKey:
    return make_ec_key()


@pytest.fixture(scope="session")
def api_settings(database_dsn: str) -> Settings:
    return IsolatedSettings(
        app_env=AppEnv.TEST,
        database_url=SecretStr(database_dsn),
        supabase_url=TEST_SUPABASE_URL,
        db_pool_max_size=4,
        # The built-in test provider: API tests queue jobs; tests that run them use the worker.
        llm_provider=LlmProviderName.FAKE,
    )


@pytest.fixture(scope="session")
def api_app(api_settings: Settings, signing_key: SigningKey) -> FastAPI:
    return create_app(api_settings, jwks_fetcher=static_jwks_fetcher(signing_key))


@pytest.fixture(scope="session")
def api(api_app: FastAPI) -> Iterator[TestClient]:
    """One application and connection pool for the whole session (see support/database.py)."""
    with new_client(api_app) as test_client:
        # Block until the pool's first connection is established, so no background connect
        # overlaps with the admin connection used by later tests.
        assert test_client.get("/readyz").status_code == 200
        yield test_client


@dataclass(frozen=True)
class Learner:
    """A real row in auth.users (and, via the trigger, public.profiles) plus a signed token."""

    id: UUID
    email: str
    token: str

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}


@pytest.fixture
def make_learner(database_dsn: str, signing_key: SigningKey) -> Callable[..., Learner]:
    def factory(*, display_name: str | None = None) -> Learner:
        user_id = create_auth_user(database_dsn, display_name=display_name)
        email = f"{user_id}@example.test"
        claims = build_claims(sub=user_id, email=email)
        return Learner(id=user_id, email=email, token=sign_with_key(signing_key, claims))

    return factory


# --- The background worker and the job queue -----------------------------------------------------


@pytest.fixture
async def database(database_dsn: str) -> AsyncIterator[Database]:
    """A connection pool onto the test database, for tests that run the worker or the queue.

    The queue starts empty: the database is shared by the whole session, so jobs left over from
    other tests are cancelled first and the worker only ever picks up this test's own job.
    """
    clear_queue(database_dsn)
    pool = Database.from_settings(worker_settings(database_dsn))
    await pool.open(wait=True)
    try:
        yield pool
    finally:
        await pool.close()


@pytest.fixture
def configure_app(
    api_app: FastAPI, api_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> Callable[..., None]:
    """Change the running app's settings for one test (restored afterwards)."""

    def apply(**changes: object) -> None:
        monkeypatch.setattr(api_app.state, "settings", api_settings.model_copy(update=changes))

    return apply


@pytest.fixture
def no_ai(configure_app: Callable[..., None]) -> None:
    """The app as deployed without an AI provider."""
    configure_app(llm_provider=None)
