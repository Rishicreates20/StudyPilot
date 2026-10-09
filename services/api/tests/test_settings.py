import pytest
from pydantic import SecretStr, ValidationError

from app.core.config import (
    EX_CONFIG,
    AppEnv,
    JwtMode,
    format_config_errors,
    load_settings_or_exit,
)
from support.settings import IsolatedSettings, valid_local_settings

PROD_DATABASE_URL = "postgresql://u:pw@db.example.com:5432/postgres?sslmode=require"


def production_settings(**overrides: object) -> IsolatedSettings:
    values: dict[str, object] = {
        "app_env": AppEnv.PRODUCTION,
        "cors_allowed_origins": ["https://app.example.com"],
        "supabase_url": "https://abcd.supabase.co",
        "database_url": SecretStr(PROD_DATABASE_URL),
    }
    values.update(overrides)
    return valid_local_settings(**values)


def test_defaults_describe_a_local_development_setup() -> None:
    settings = valid_local_settings()

    assert settings.app_env is AppEnv.LOCAL
    assert settings.app_name == "StudyPilot"
    assert settings.cors_allowed_origins == ["http://localhost:3000"]
    assert settings.supabase_jwt_mode is JwtMode.JWKS
    assert settings.docs_enabled is True
    assert settings.json_logs is False


def test_the_token_issuer_and_key_url_are_derived_from_the_supabase_url() -> None:
    settings = valid_local_settings(supabase_url="https://abcd.supabase.co/")

    assert settings.supabase_url == "https://abcd.supabase.co"
    assert settings.jwt_issuer == "https://abcd.supabase.co/auth/v1"
    assert settings.jwks_url == "https://abcd.supabase.co/auth/v1/.well-known/jwks.json"


def test_environment_variables_override_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_NAME", "Custom Name")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "http://localhost:3000, http://127.0.0.1:3000/")
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:pw@localhost:5432/postgres")
    monkeypatch.setenv("SUPABASE_URL", "http://127.0.0.1:54321")

    settings = IsolatedSettings()

    assert settings.app_name == "Custom Name"
    assert settings.log_level == "DEBUG"
    assert settings.cors_allowed_origins == ["http://localhost:3000", "http://127.0.0.1:3000"]
    assert settings.supabase_url == "http://127.0.0.1:54321"


def test_secrets_never_appear_in_repr_or_str() -> None:
    settings = valid_local_settings(
        database_url=SecretStr("postgresql://app:hunter2@db.example.com:5432/postgres"),
        supabase_jwt_mode=JwtMode.HS256,
        supabase_jwt_secret=SecretStr("x" * 40 + "-jwt-secret"),
    )

    text = f"{settings!r} {settings}"

    assert "hunter2" not in text
    assert "-jwt-secret" not in text


@pytest.mark.parametrize(
    "origin", ["*", "localhost:3000", "ftp://example.com", "https://a.com/app"]
)
def test_malformed_cors_origins_are_rejected(origin: str) -> None:
    with pytest.raises(ValidationError):
        valid_local_settings(cors_allowed_origins=[origin])


@pytest.mark.parametrize("env", [AppEnv.STAGING, AppEnv.PRODUCTION])
def test_insecure_origins_are_rejected_outside_local_and_test(env: AppEnv) -> None:
    with pytest.raises(ValidationError, match="https"):
        production_settings(app_env=env, cors_allowed_origins=["http://app.example.com"])


def test_production_uses_json_logs_and_disables_docs() -> None:
    settings = production_settings()

    assert settings.json_logs is True
    assert settings.docs_enabled is False


# --- Database and Supabase configuration -----------------------------------------------------


def test_a_non_test_environment_requires_both_database_and_supabase_settings() -> None:
    with pytest.raises(ValidationError) as caught:
        IsolatedSettings()

    report = format_config_errors(caught.value)
    assert "DATABASE_URL" in report
    assert "SUPABASE_URL" in report


def test_the_test_environment_may_omit_them() -> None:
    settings = IsolatedSettings(app_env=AppEnv.TEST)

    assert settings.database_url is None
    assert settings.jwt_issuer is None


@pytest.mark.parametrize("url", ["mysql://u:p@h/db", "not a url", "postgresql:///nohost"])
def test_database_url_must_be_a_postgres_url_and_is_never_echoed(url: str) -> None:
    with pytest.raises(ValidationError) as caught:
        valid_local_settings(database_url=SecretStr(url))

    assert url not in format_config_errors(caught.value)


@pytest.mark.parametrize("suffix", ["", "?sslmode=disable", "?sslmode=prefer"])
def test_staging_and_production_require_tls_to_the_database(suffix: str) -> None:
    with pytest.raises(ValidationError, match="sslmode"):
        production_settings(
            database_url=SecretStr(f"postgresql://u:pw@db.example.com:5432/postgres{suffix}")
        )


def test_production_requires_an_https_supabase_url() -> None:
    with pytest.raises(ValidationError, match="SUPABASE_URL must use https"):
        production_settings(supabase_url="http://abcd.supabase.co")


def test_hs256_mode_requires_a_long_enough_secret() -> None:
    with pytest.raises(ValidationError, match="SUPABASE_JWT_SECRET"):
        valid_local_settings(supabase_jwt_mode=JwtMode.HS256)
    with pytest.raises(ValidationError, match="SUPABASE_JWT_SECRET"):
        valid_local_settings(
            supabase_jwt_mode=JwtMode.HS256, supabase_jwt_secret=SecretStr("short")
        )

    settings = valid_local_settings(
        supabase_jwt_mode=JwtMode.HS256, supabase_jwt_secret=SecretStr("s" * 32)
    )
    assert settings.supabase_jwt_mode is JwtMode.HS256


def test_pool_bounds_are_checked() -> None:
    with pytest.raises(ValidationError, match="DB_POOL_MIN_SIZE"):
        valid_local_settings(db_pool_min_size=5, db_pool_max_size=2)


# --- Startup behaviour -----------------------------------------------------------------------


def test_error_report_names_variables_but_never_echoes_values() -> None:
    with pytest.raises(ValidationError) as caught:
        valid_local_settings(app_env="hunter2", log_level="shout")

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
