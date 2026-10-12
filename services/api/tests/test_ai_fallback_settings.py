"""LLM_FALLBACKS: the extra providers behind the main one, as configuration."""

import json
from typing import Any

import httpx2
import pytest
from pydantic import SecretStr, ValidationError

from app.ai.chain import ProviderChain
from app.ai.factory import build_provider
from app.ai.fake import FakeProvider
from app.ai.fallback_config import MAX_PROVIDERS, FallbackConfigError, parse_fallbacks
from app.ai.gemini import GeminiProvider
from app.core.config import format_config_errors
from support.settings import valid_local_settings

API_KEY = "nvapi-this-is-a-secret-key-1234567890"


def entry(**fields: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "name": "nvidia",
        "base_url": "https://integrate.api.nvidia.com/v1",
        "api_key": API_KEY,
        "models": ["z-ai/glm-5.3-flash", "deepseek-ai/deepseek-v4.1-flash"],
    }
    values.update(fields)
    return values


def raw(*entries: dict[str, Any]) -> str:
    return json.dumps(list(entries))


def test_a_provider_is_read_with_sensible_defaults() -> None:
    (provider,) = parse_fallbacks(raw(entry()))

    assert provider.name == "nvidia"
    assert provider.base_url == "https://integrate.api.nvidia.com/v1"
    assert provider.models == ("z-ai/glm-5.3-flash", "deepseek-ai/deepseek-v4.1-flash")
    assert provider.api_key.get_secret_value() == API_KEY
    assert provider.json_mode == "object" and provider.max_output_tokens == 16000


def test_several_providers_keep_their_order() -> None:
    names = [
        p.name
        for p in parse_fallbacks(
            raw(entry(), entry(name="openrouter", base_url="https://openrouter.ai/api/v1/"))
        )
    ]

    assert names == ["nvidia", "openrouter"]


def test_a_trailing_slash_on_the_base_url_is_removed() -> None:
    (provider,) = parse_fallbacks(raw(entry(base_url="https://api.example.com/v1/")))

    assert provider.base_url == "https://api.example.com/v1"


def test_plain_http_is_allowed_only_for_a_server_on_this_machine() -> None:
    (local,) = parse_fallbacks(raw(entry(name="ollama", base_url="http://localhost:11434/v1")))

    assert local.base_url == "http://localhost:11434/v1"
    with pytest.raises(FallbackConfigError, match="https"):
        parse_fallbacks(raw(entry(base_url="http://api.example.com/v1")))


@pytest.mark.parametrize(
    ("bad", "mentions"),
    [
        (entry(name="Gemini"), "name"),
        (entry(name="gemini"), "name"),
        (entry(name="fake"), "name"),
        (entry(name="has space"), "name"),
        (entry(name=""), "name"),
        (entry(base_url="not a url"), "base_url"),
        (entry(base_url="https://user:pw@api.example.com/v1"), "base_url"),
        (entry(base_url="https://api.example.com/v1?key=1"), "base_url"),
        (entry(api_key=""), "api_key"),
        (entry(models=[]), "models"),
        (entry(models=["ok", "ok"]), "models"),
        (entry(models=["has space"]), "models"),
        (entry(models=["a"] * 9), "models"),
        (entry(max_output_tokens=10), "max_output_tokens"),
        (entry(json_mode="yaml"), "json_mode"),
        (entry(apikey="typo"), "apikey"),
    ],
)
def test_a_bad_entry_is_refused_and_the_message_names_the_field(
    bad: dict[str, Any], mentions: str
) -> None:
    with pytest.raises(FallbackConfigError) as raised:
        parse_fallbacks(raw(bad))

    assert mentions in str(raised.value) and "provider 1" in str(raised.value)


@pytest.mark.parametrize(
    "text",
    ["", "not json", '{"name": "x"}', '"a string"', "42", "[1, 2]", "[null]"],
)
def test_anything_but_a_list_of_providers_is_refused(text: str) -> None:
    with pytest.raises(FallbackConfigError):
        parse_fallbacks(text)


def test_the_same_name_twice_is_refused() -> None:
    with pytest.raises(FallbackConfigError, match="different"):
        parse_fallbacks(raw(entry(), entry()))


def test_too_many_providers_are_refused() -> None:
    many = [entry(name=f"p{n}") for n in range(MAX_PROVIDERS + 1)]

    with pytest.raises(FallbackConfigError, match="at most"):
        parse_fallbacks(raw(*many))


def test_no_error_message_ever_contains_a_key_or_a_value() -> None:
    mistakes = [
        raw(entry(name="gemini")),
        raw(entry(base_url="http://insecure.example.com")),
        raw(entry(models=[API_KEY + " with space"])),
        raw(entry(json_mode="yaml"), entry()),
        raw(entry(apikey=API_KEY)),
        "[" + API_KEY,
    ]

    for text in mistakes:
        with pytest.raises(FallbackConfigError) as raised:
            parse_fallbacks(text)
        assert API_KEY not in str(raised.value)


# --- As part of the settings -----------------------------------------------------------------


def test_no_fallbacks_is_the_default() -> None:
    settings = valid_local_settings()

    assert settings.llm_fallbacks is None
    assert settings.llm_fallback_providers == ()


def test_a_blank_value_means_no_fallbacks() -> None:
    assert valid_local_settings(llm_fallbacks="   ").llm_fallbacks is None


def test_the_settings_carry_the_parsed_providers() -> None:
    settings = valid_local_settings(llm_fallbacks=SecretStr(raw(entry())))

    assert [p.name for p in settings.llm_fallback_providers] == ["nvidia"]


def test_the_keys_never_appear_in_the_settings_repr() -> None:
    settings = valid_local_settings(llm_fallbacks=SecretStr(raw(entry())))

    assert API_KEY not in repr(settings) and API_KEY not in str(settings)


def test_a_bad_value_stops_startup_with_a_message_that_has_no_secret_in_it() -> None:
    with pytest.raises(ValidationError) as raised:
        valid_local_settings(llm_fallbacks=SecretStr(raw(entry(name="gemini", api_key=API_KEY))))

    message = format_config_errors(raised.value)
    assert "LLM_FALLBACKS" in message and "provider 1" in message
    assert API_KEY not in message


# --- The factory -----------------------------------------------------------------------------


def build(**settings: Any) -> object:
    client = httpx2.AsyncClient(transport=httpx2.MockTransport(lambda _r: httpx2.Response(500)))
    return build_provider(valid_local_settings(**settings), client)


def test_without_fallbacks_the_provider_is_plain_gemini() -> None:
    provider = build(llm_provider="gemini", gemini_api_key=SecretStr("k"))

    assert isinstance(provider, GeminiProvider)


def test_with_fallbacks_gemini_is_wrapped_in_a_chain_that_still_calls_itself_gemini() -> None:
    provider = build(
        llm_provider="gemini",
        gemini_api_key=SecretStr("k"),
        llm_fallbacks=SecretStr(raw(entry(), entry(name="openrouter"))),
    )

    assert isinstance(provider, ProviderChain)
    assert provider.name == "gemini"


def test_the_test_provider_is_never_wrapped() -> None:
    provider = build(llm_provider="fake", llm_fallbacks=SecretStr(raw(entry())))

    assert isinstance(provider, FakeProvider)
