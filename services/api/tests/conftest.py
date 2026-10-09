from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from helpers import IsolatedSettings

from app.core.config import AppEnv, Settings
from app.main import create_app

_CONFIG_VARIABLES = ("APP_ENV", "APP_NAME", "APP_VERSION", "LOG_LEVEL", "CORS_ALLOWED_ORIGINS")


@pytest.fixture(autouse=True)
def _isolated_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests must not depend on the developer's shell environment."""
    for name in _CONFIG_VARIABLES:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def settings() -> Settings:
    return IsolatedSettings(app_env=AppEnv.TEST)


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    return create_app(settings)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    # raise_server_exceptions=False: exercise the real 500 handler instead of re-raising.
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
