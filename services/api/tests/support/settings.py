"""Test-only helpers."""

from pydantic_settings import SettingsConfigDict

from app.core.config import Settings


class IsolatedSettings(Settings):
    """Settings that ignore any local ``.env`` file, so tests depend only on explicit inputs."""

    model_config = SettingsConfigDict(env_file=None, extra="ignore", case_sensitive=False)
