"""Application settings, validated once at startup.

Configuration comes from environment variables (and an optional local ``.env`` file).
Invalid or missing configuration stops the process with a readable message that lists
variable names and reasons but never echoes the supplied values, so secrets cannot leak
into logs or terminals.
"""

import sys
from enum import StrEnum
from functools import lru_cache
from typing import Annotated, Literal, Self
from urllib.parse import urlparse

from pydantic import ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

EX_CONFIG = 78  # sysexits.h: configuration error


class AppEnv(StrEnum):
    LOCAL = "local"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: AppEnv = AppEnv.LOCAL
    app_name: str = "StudyPilot"
    app_version: str = "0.1.0"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    # Comma-separated in the environment, e.g. "http://localhost:3000,https://app.example.com".
    cors_allowed_origins: Annotated[list[str], NoDecode] = ["http://localhost:3000"]

    @field_validator("cors_allowed_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return value

    @field_validator("cors_allowed_origins")
    @classmethod
    def _validate_origins(cls, origins: list[str]) -> list[str]:
        for origin in origins:
            parsed = urlparse(origin)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError("each origin must look like http(s)://host[:port]")
            if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
                raise ValueError("origins must not include a path, query or fragment")
        return [origin.rstrip("/") for origin in origins]

    @model_validator(mode="after")
    def _require_https_outside_local(self) -> Self:
        if self.app_env in {AppEnv.STAGING, AppEnv.PRODUCTION}:
            insecure = [o for o in self.cors_allowed_origins if not o.startswith("https://")]
            if insecure:
                raise ValueError("CORS_ALLOWED_ORIGINS must use https in staging and production")
        return self

    @property
    def docs_enabled(self) -> bool:
        """Interactive API docs are available everywhere except production."""
        return self.app_env is not AppEnv.PRODUCTION

    @property
    def json_logs(self) -> bool:
        """Human-readable logs locally, machine-readable JSON everywhere else."""
        return self.app_env is not AppEnv.LOCAL


def format_config_errors(exc: ValidationError) -> str:
    """Render a validation error as variable names and reasons only (never input values)."""
    lines = ["Invalid configuration - fix the following environment variables:"]
    for error in exc.errors(include_input=False, include_url=False):
        location = ".".join(str(part) for part in error["loc"]) or "settings"
        message = error["msg"].removeprefix("Value error, ")
        lines.append(f"  - {location.upper()}: {message}")
    return "\n".join(lines)


def load_settings_or_exit() -> Settings:
    """Load settings, or print a clean message and exit with EX_CONFIG."""
    try:
        return Settings()
    except ValidationError as exc:
        sys.stderr.write(format_config_errors(exc) + "\n")
        raise SystemExit(EX_CONFIG) from None


@lru_cache
def get_settings() -> Settings:
    return load_settings_or_exit()
