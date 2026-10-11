"""Configuration of the AI provider and the job system."""

import httpx2
import pytest
from pydantic import SecretStr, ValidationError

from app.ai.factory import build_provider
from app.ai.fake import FakeProvider
from app.ai.gemini import GeminiProvider
from app.ai.provider import LLMNotConfigured
from app.core.config import AppEnv, LlmProviderName
from support.settings import valid_local_settings

PRODUCTION: dict[str, object] = {
    "app_env": AppEnv.PRODUCTION,
    "cors_allowed_origins": ["https://app.example.com"],
    "supabase_url": "https://abcd.supabase.co",
    "database_url": SecretStr("postgresql://u:pw@db.example.com:5432/postgres?sslmode=require"),
}


def test_ai_is_off_until_a_provider_is_chosen() -> None:
    settings = valid_local_settings()

    assert settings.llm_provider is None
    assert settings.ai_configured is False


def test_gemini_needs_its_key_to_count_as_configured() -> None:
    assert valid_local_settings(llm_provider="gemini").ai_configured is False
    assert (
        valid_local_settings(llm_provider="gemini", gemini_api_key=SecretStr("k")).ai_configured
        is True
    )


def test_blank_values_in_the_environment_file_mean_unset() -> None:
    settings = valid_local_settings(llm_provider="  ", gemini_api_key="  ")

    assert settings.llm_provider is None
    assert settings.gemini_api_key is None


def test_the_fake_provider_is_allowed_locally() -> None:
    settings = valid_local_settings(llm_provider="fake")

    assert settings.llm_provider is LlmProviderName.FAKE
    assert settings.ai_configured is True


@pytest.mark.parametrize("environment", [AppEnv.STAGING, AppEnv.PRODUCTION])
def test_the_fake_provider_is_refused_in_staging_and_production(environment: AppEnv) -> None:
    with pytest.raises(ValidationError, match="not allowed in staging or production"):
        valid_local_settings(**{**PRODUCTION, "app_env": environment, "llm_provider": "fake"})


def test_real_providers_are_fine_in_production() -> None:
    settings = valid_local_settings(
        **PRODUCTION, llm_provider="gemini", gemini_api_key=SecretStr("k")
    )

    assert settings.ai_configured is True


def test_the_key_never_appears_in_the_settings_repr() -> None:
    settings = valid_local_settings(llm_provider="gemini", gemini_api_key=SecretStr("sekrit-key"))

    assert "sekrit-key" not in repr(settings)


def test_the_model_base_url_must_be_a_url() -> None:
    with pytest.raises(ValidationError):
        valid_local_settings(gemini_base_url="not a url")


def test_job_and_provider_defaults_are_sensible() -> None:
    settings = valid_local_settings()

    assert settings.gemini_model == "gemini-3.6-flash"
    assert settings.job_max_attempts == 3
    assert settings.worker_concurrency == 1
    assert settings.roadmap_jobs_per_user_per_day >= 1
    assert settings.lesson_jobs_per_user_per_day >= 1
    assert 1 <= settings.lesson_jobs_active_per_user <= 10


@pytest.mark.parametrize("name", ["lesson_jobs_per_user_per_day", "lesson_jobs_active_per_user"])
@pytest.mark.parametrize("value", [0, -1])
def test_lesson_limits_must_be_positive(name: str, value: int) -> None:
    with pytest.raises(ValidationError):
        valid_local_settings(**{name: value})


# --- Choosing a provider ---------------------------------------------------------------------


def test_the_factory_builds_the_configured_provider() -> None:
    client = httpx2.AsyncClient()

    gemini = build_provider(
        valid_local_settings(llm_provider="gemini", gemini_api_key=SecretStr("k")), client
    )
    fake = build_provider(valid_local_settings(llm_provider="fake"), client)

    assert isinstance(gemini, GeminiProvider)
    assert isinstance(fake, FakeProvider)


def test_the_factory_refuses_when_nothing_is_configured() -> None:
    client = httpx2.AsyncClient()

    with pytest.raises(LLMNotConfigured):
        build_provider(valid_local_settings(), client)
    with pytest.raises(LLMNotConfigured):
        build_provider(valid_local_settings(llm_provider="gemini"), client)
