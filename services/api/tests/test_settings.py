import pytest
from helpers import IsolatedSettings
from pydantic import ValidationError

from app.core.config import (
    EX_CONFIG,
    AppEnv,
    format_config_errors,
    load_settings_or_exit,
)


def test_defaults_describe_a_local_development_setup() -> None:
    settings = IsolatedSettings()

    assert settings.app_env is AppEnv.LOCAL
    assert settings.app_name == "StudyPilot"
    assert settings.cors_allowed_origins == ["http://localhost:3000"]
    assert settings.docs_enabled is True
    assert settings.json_logs is False


def test_environment_variables_override_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_NAME", "Custom Name")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "http://localhost:3000, http://127.0.0.1:3000/")

    settings = IsolatedSettings()

    assert settings.app_name == "Custom Name"
    assert settings.log_level == "DEBUG"
    assert settings.cors_allowed_origins == ["http://localhost:3000", "http://127.0.0.1:3000"]


@pytest.mark.parametrize(
    "origin", ["*", "localhost:3000", "ftp://example.com", "https://a.com/app"]
)
def test_malformed_cors_origins_are_rejected(origin: str) -> None:
    with pytest.raises(ValidationError):
        IsolatedSettings(cors_allowed_origins=[origin])


@pytest.mark.parametrize("env", [AppEnv.STAGING, AppEnv.PRODUCTION])
def test_insecure_origins_are_rejected_outside_local_and_test(env: AppEnv) -> None:
    with pytest.raises(ValidationError, match="https"):
        IsolatedSettings(app_env=env, cors_allowed_origins=["http://app.example.com"])


def test_production_uses_json_logs_and_disables_docs() -> None:
    settings = IsolatedSettings(
        app_env=AppEnv.PRODUCTION,
        cors_allowed_origins=["https://app.example.com"],
    )

    assert settings.json_logs is True
    assert settings.docs_enabled is False


def test_error_report_names_variables_but_never_echoes_values() -> None:
    with pytest.raises(ValidationError) as caught:
        IsolatedSettings(app_env="hunter2", log_level="shout")  # pyright: ignore[reportArgumentType]

    report = format_config_errors(caught.value)

    assert "APP_ENV" in report
    assert "LOG_LEVEL" in report
    assert "hunter2" not in report
    assert "shout" not in report


def test_startup_exits_with_a_config_error_code_and_a_clean_message(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("APP_ENV", "hunter2")

    with pytest.raises(SystemExit) as exit_info:
        load_settings_or_exit()

    assert exit_info.value.code == EX_CONFIG
    stderr = capsys.readouterr().err
    assert "APP_ENV" in stderr
    assert "hunter2" not in stderr
    assert "Traceback" not in stderr
