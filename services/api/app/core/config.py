"""Application settings, validated once at startup.

Configuration comes from environment variables (and an optional local ``.env`` file).
Invalid or missing configuration stops the process with a readable message that lists
variable names and reasons but never echoes the supplied values, so secrets cannot leak
into logs or terminals. Secrets are typed ``SecretStr`` so they also never appear in
``repr()`` output.
"""

import re
import sys
from enum import StrEnum
from functools import lru_cache
from typing import Annotated, Literal, Self
from urllib.parse import parse_qs, urlparse

from pydantic import Field, SecretStr, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

EX_CONFIG = 78  # sysexits.h: configuration error

_SECURE_SSL_MODES = frozenset({"require", "verify-ca", "verify-full"})
_MIN_HS256_SECRET_LENGTH = 32


class AppEnv(StrEnum):
    LOCAL = "local"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"


class JwtMode(StrEnum):
    """How access tokens issued by Supabase Auth are verified."""

    JWKS = "jwks"  # asymmetric signing keys (ES256/RS256), fetched from the project's JWKS URL
    HS256 = "hs256"  # legacy shared JWT secret; also what the local Supabase CLI stack uses


class LlmProviderName(StrEnum):
    """Which model provider the worker talks to. Unset means the AI features are switched off."""

    GEMINI = "gemini"
    FAKE = "fake"  # a deterministic test double; refused in staging and production


class DocumentStorageName(StrEnum):
    """Where uploaded files are kept (never in a public bucket, never served inline)."""

    SUPABASE = "supabase"  # a private Supabase Storage bucket, reached with the learner's own token
    LOCAL = "local"  # a folder on this machine: local development and tests, refused in production


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

    # --- Database (Supabase PostgreSQL) ---------------------------------------------------------
    # Required except in tests. Contains the database password: a secret, server-only.
    database_url: SecretStr | None = None
    db_pool_min_size: int = Field(default=1, ge=0, le=50)
    db_pool_max_size: int = Field(default=10, ge=1, le=100)
    db_pool_timeout_seconds: float = Field(default=5.0, gt=0, le=60)

    # --- Supabase Auth (token verification) -----------------------------------------------------
    supabase_url: str | None = None
    supabase_jwt_mode: JwtMode = JwtMode.JWKS
    # Only for supabase_jwt_mode=hs256. A secret: it can mint tokens for any user.
    supabase_jwt_secret: SecretStr | None = None
    supabase_jwt_audience: str = "authenticated"
    # Default: {SUPABASE_URL}/auth/v1
    supabase_jwt_issuer: str | None = None
    # Default: {SUPABASE_URL}/auth/v1/.well-known/jwks.json
    supabase_jwks_url: str | None = None
    jwt_leeway_seconds: int = Field(default=10, ge=0, le=60)

    # --- Product limits -------------------------------------------------------------------------
    max_active_goals_per_user: int = Field(default=50, ge=1, le=1000)
    # Roadmap generations a learner may start per rolling 24 hours (a guard against runaway cost).
    roadmap_jobs_per_user_per_day: int = Field(default=20, ge=1, le=1000)
    # Lessons a learner may have written per rolling 24 hours, and how many may be in progress at
    # once (each is a model call; a learner reading one topic rarely needs more than two waiting).
    lesson_jobs_per_user_per_day: int = Field(default=60, ge=1, le=2000)
    lesson_jobs_active_per_user: int = Field(default=2, ge=1, le=10)
    # Quizzes a learner may have written per rolling 24 hours (each is a model call), and the shape
    # of one: how many questions, and how many of them are short answers (graded by a model).
    quiz_jobs_per_user_per_day: int = Field(default=30, ge=1, le=1000)
    quiz_question_count: int = Field(default=5, ge=3, le=10)
    quiz_short_answers: int = Field(default=1, ge=0, le=2)

    # --- Mastery (transparent product rules, not model output; see app/learning/mastery.py) -----
    # A topic scoring below the first threshold needs practice; from the second it counts as
    # mastered; in between it is progressing.
    mastery_needs_practice_below: float = Field(default=70.0, ge=1, le=99)
    mastery_mastered_from: float = Field(default=90.0, ge=2, le=100)
    # Each older attempt counts this much of the one after it (1 = all attempts count equally).
    mastery_recency_decay: float = Field(default=0.7, gt=0, le=1)
    # Fewer answers than this and a score is shown as an early estimate.
    mastery_min_answers: int = Field(default=4, ge=1, le=50)

    # --- Documents: uploads, extraction, embeddings and retrieval (ADR-039...043) -------------
    # The publishable key is public by design. The Storage gateway wants it next to the learner's
    # own token; the API never needs (and this project never uses) the service-role key.
    supabase_publishable_key: str | None = None
    document_storage: DocumentStorageName = DocumentStorageName.SUPABASE
    # Only for DOCUMENT_STORAGE=local (a path relative to the API's working directory is fine).
    document_local_dir: str = Field(default=".data/documents", min_length=1, max_length=300)
    document_bucket: str = Field(default="documents", pattern=r"^[a-z0-9][a-z0-9_-]{1,62}$")
    # What one uploaded file, and the text taken from it, may weigh. Larger is refused up front.
    document_max_bytes: int = Field(default=10 * 1024 * 1024, ge=1024, le=50 * 1024 * 1024)
    document_max_pages: int = Field(default=300, ge=1, le=2000)
    document_max_chars: int = Field(default=1_000_000, ge=1000, le=5_000_000)
    # Pages of one document that may be read by the vision model (each is a model call).
    document_max_ocr_pages: int = Field(default=20, ge=0, le=100)
    documents_per_goal: int = Field(default=20, ge=1, le=500)
    documents_per_user: int = Field(default=100, ge=1, le=5000)
    # Document jobs (processing, re-processing, indexing after a review) per rolling 24 hours.
    document_jobs_per_user_per_day: int = Field(default=100, ge=1, le=2000)
    # How long the signed link that lets the worker read an uploaded file stays valid.
    document_signed_url_seconds: int = Field(default=3600, ge=60, le=86400)
    # The vectors are 1536 numbers (the database column is fixed at that size, ADR-008); the model
    # name is recorded with every chunk so a change is visible and can be re-indexed.
    embedding_model: str = Field(default="gemini-embedding-001", min_length=1, max_length=100)
    # Chunks are about this long (in characters) with this much repeated from the one before.
    chunk_target_chars: int = Field(default=1200, ge=300, le=4000)
    chunk_overlap_chars: int = Field(default=200, ge=0, le=1000)
    # Passages a lesson (or a search) gets, and how similar one must be to the question to count.
    retrieval_top_k: int = Field(default=6, ge=1, le=20)
    retrieval_min_similarity: float = Field(default=0.58, ge=0, le=1)
    # Searches a learner may run per rolling hour: each embeds one short query with the provider.
    document_searches_per_user_per_hour: int = Field(default=120, ge=1, le=5000)

    # --- Exports: PDF notes, revision sheets, roadmaps and slides (ADR-049) -------------------
    # Stored in a second private bucket, through the same store as documents (DOCUMENT_STORAGE).
    export_bucket: str = Field(default="exports", pattern=r"^[a-z0-9][a-z0-9_-]{1,62}$")
    # Only for DOCUMENT_STORAGE=local.
    export_local_dir: str = Field(default=".data/exports", min_length=1, max_length=300)
    # How long a download link stays valid. Short: the browser follows it at once.
    export_download_seconds: int = Field(default=120, ge=30, le=3600)
    # Export jobs one learner may start per rolling 24 hours (each renders a file).
    export_jobs_per_user_per_day: int = Field(default=40, ge=1, le=1000)

    # --- AI provider (used by the worker; the API only checks that it is configured) -----------
    llm_provider: LlmProviderName | None = None
    # A secret: server-only, never logged, never sent to the browser.
    gemini_api_key: SecretStr | None = None
    # Measured on the owner's key (2026-10-11), same roadmap request: gemini-3.5-flash-lite 6 s,
    # gemini-3.6-flash 18 s, gemini-3.8-flash 96 s (and "high demand" 503s at other times).
    gemini_model: str = Field(default="gemini-3.6-flash", min_length=1, max_length=100)
    # Other models to try, in order, when the one above has used up its allowance or is overloaded.
    # A free-tier key has a separate daily allowance per model, so a list stretches it. Comma
    # separated; an empty value means no fallback.
    gemini_fallback_models: str = Field(default="", max_length=500)
    # How much a Gemini 3 model may "think" before it answers. Thinking tokens come out of the same
    # output budget as the answer, so a high level makes long documents slow and can cut them off
    # (MAX_TOKENS). "low" is much faster for the structured writing this app asks for. Empty means
    # the model's own default. A model that does not accept the level is asked without it.
    gemini_thinking_level: Literal["", "minimal", "low", "medium", "high"] = ""
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    llm_timeout_seconds: float = Field(default=180.0, gt=0, le=600)
    llm_max_output_tokens: int = Field(default=24000, ge=1024, le=65536)
    llm_temperature: float = Field(default=0.4, ge=0, le=2)

    # --- Background jobs and the worker process ------------------------------------------------
    job_max_attempts: int = Field(default=3, ge=1, le=10)
    # How long a claimed job stays locked without a heartbeat before another worker may take it.
    job_lease_seconds: int = Field(default=90, ge=5, le=900)
    # First retry waits about this long; later retries double it (with jitter), capped at 5 minutes.
    job_retry_base_seconds: float = Field(default=5.0, ge=0, le=600)
    worker_poll_seconds: float = Field(default=2.0, gt=0, le=60)
    worker_concurrency: int = Field(default=1, ge=1, le=8)

    @field_validator("supabase_publishable_key", mode="before")
    @classmethod
    def _blank_publishable_key_is_unset(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

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

    @field_validator("supabase_url", mode="before")
    @classmethod
    def _blank_url_is_unset(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("supabase_url")
    @classmethod
    def _validate_supabase_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = urlparse(value.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("must look like https://<project-ref>.supabase.co")
        if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            raise ValueError("must not include a path, query or fragment")
        return f"{parsed.scheme}://{parsed.netloc}"

    @field_validator("database_url", "supabase_jwt_secret", "gemini_api_key", mode="before")
    @classmethod
    def _blank_secret_is_unset(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("llm_provider", mode="before")
    @classmethod
    def _blank_provider_is_unset(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("gemini_base_url")
    @classmethod
    def _validate_gemini_base_url(cls, value: str) -> str:
        parsed = urlparse(value.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("must look like https://generativelanguage.googleapis.com/v1beta")
        return value.strip().rstrip("/")

    @field_validator("database_url")
    @classmethod
    def _validate_database_url(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None:
            return None
        parsed = urlparse(value.get_secret_value())
        if parsed.scheme not in {"postgresql", "postgres"} or not parsed.hostname:
            raise ValueError("must look like postgresql://user:password@host:5432/postgres")
        return value

    @model_validator(mode="after")
    def _validate_cross_field_rules(self) -> Self:
        hardened = self.app_env in {AppEnv.STAGING, AppEnv.PRODUCTION}

        if hardened:
            if any(not o.startswith("https://") for o in self.cors_allowed_origins):
                raise ValueError("CORS_ALLOWED_ORIGINS must use https in staging and production")
            if self.supabase_url and not self.supabase_url.startswith("https://"):
                raise ValueError("SUPABASE_URL must use https in staging and production")
            if self.database_url is not None:
                query = parse_qs(urlparse(self.database_url.get_secret_value()).query)
                if query.get("sslmode", [""])[0] not in _SECURE_SSL_MODES:
                    raise ValueError(
                        "DATABASE_URL must set sslmode=require (or verify-*) in staging and "
                        "production"
                    )

        if self.app_env is not AppEnv.TEST:
            missing = [
                name
                for name, value in (
                    ("DATABASE_URL", self.database_url),
                    ("SUPABASE_URL", self.supabase_url),
                )
                if value is None
            ]
            if missing:
                raise ValueError(
                    f"{' and '.join(missing)} must be set (see docs/SUPABASE_SETUP.md)"
                )

        if self.supabase_jwt_mode is JwtMode.HS256:
            secret = self.supabase_jwt_secret
            if secret is None or len(secret.get_secret_value()) < _MIN_HS256_SECRET_LENGTH:
                raise ValueError(
                    f"SUPABASE_JWT_SECRET must be set (at least {_MIN_HS256_SECRET_LENGTH} "
                    "characters) when SUPABASE_JWT_MODE=hs256"
                )
        if self.db_pool_min_size > self.db_pool_max_size:
            raise ValueError("DB_POOL_MIN_SIZE must not exceed DB_POOL_MAX_SIZE")
        if self.mastery_needs_practice_below >= self.mastery_mastered_from:
            raise ValueError(
                "MASTERY_NEEDS_PRACTICE_BELOW must be lower than MASTERY_MASTERED_FROM"
            )
        if self.chunk_overlap_chars >= self.chunk_target_chars // 2:
            raise ValueError("CHUNK_OVERLAP_CHARS must be less than half of CHUNK_TARGET_CHARS")
        if hardened and self.document_storage is DocumentStorageName.LOCAL:
            raise ValueError(
                "DOCUMENT_STORAGE=local keeps files on this machine's disk and is not allowed in "
                "staging or production"
            )
        if hardened and self.llm_provider is LlmProviderName.FAKE:
            raise ValueError(
                "LLM_PROVIDER=fake is a test double and is not allowed in staging or production"
            )
        return self

    @field_validator("gemini_fallback_models")
    @classmethod
    def _check_fallback_models(cls, value: str) -> str:
        names = [part.strip() for part in value.split(",") if part.strip()]
        for name in names:
            if not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", name):
                raise ValueError("GEMINI_FALLBACK_MODELS must be comma-separated model names")
        return ",".join(names)

    @property
    def gemini_models(self) -> tuple[str, ...]:
        """The model to use first, then the fallbacks, each once and in order."""
        names = [self.gemini_model, *self.gemini_fallback_models.split(",")]
        return tuple(dict.fromkeys(name for name in names if name))

    @property
    def ai_configured(self) -> bool:
        """Whether a roadmap can be generated: a provider is chosen and has what it needs."""
        if self.llm_provider is LlmProviderName.FAKE:
            return True
        return self.llm_provider is LlmProviderName.GEMINI and self.gemini_api_key is not None

    @property
    def docs_enabled(self) -> bool:
        """Interactive API docs are available everywhere except production."""
        return self.app_env is not AppEnv.PRODUCTION

    @property
    def json_logs(self) -> bool:
        """Human-readable logs locally, machine-readable JSON everywhere else."""
        return self.app_env is not AppEnv.LOCAL

    @property
    def jwt_issuer(self) -> str | None:
        if self.supabase_jwt_issuer:
            return self.supabase_jwt_issuer
        return f"{self.supabase_url}/auth/v1" if self.supabase_url else None

    @property
    def jwks_url(self) -> str | None:
        if self.supabase_jwks_url:
            return self.supabase_jwks_url
        return f"{self.supabase_url}/auth/v1/.well-known/jwks.json" if self.supabase_url else None


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
