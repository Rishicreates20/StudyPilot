"""Test-only settings helpers."""

from typing import Any

from pydantic import SecretStr
from pydantic_settings import SettingsConfigDict

from app.core.config import Settings

TEST_SUPABASE_URL = "http://supabase.test"
TEST_ISSUER = f"{TEST_SUPABASE_URL}/auth/v1"
TEST_AUDIENCE = "authenticated"
# Syntactically valid but unreachable: for tests that never open a connection.
UNREACHABLE_DATABASE_URL = "postgresql://postgres:postgres@127.0.0.1:1/postgres"


class IsolatedSettings(Settings):
    """Settings that ignore any local ``.env`` file, so tests depend only on explicit inputs."""

    model_config = SettingsConfigDict(env_file=None, extra="ignore", case_sensitive=False)


def valid_local_settings(**overrides: Any) -> IsolatedSettings:
    """A complete, valid ``local`` configuration (database and Supabase both set)."""
    values: dict[str, Any] = {
        "database_url": SecretStr(UNREACHABLE_DATABASE_URL),
        "supabase_url": TEST_SUPABASE_URL,
    }
    values.update(overrides)
    return IsolatedSettings(**values)
