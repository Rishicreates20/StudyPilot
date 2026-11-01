"""Settings for the extra OpenAI-compatible providers a server can fall back to.

``LLM_FALLBACKS`` is one environment variable holding a JSON list, so any provider that speaks
the OpenAI chat format (Groq, Mistral, Cerebras, NVIDIA NIM, OpenRouter, a local Ollama...) can be
added without code:

    LLM_FALLBACKS=[{"name": "nvidia", "base_url": "https://integrate.api.nvidia.com/v1",
                    "api_key": "...", "models": ["z-ai/glm-5.3-flash"]}]

The whole value is treated as a secret (it carries the keys). Errors name the entry and the field
and never repeat a value, so a typo cannot print a key into a log.
"""

import json
import re
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError, field_validator

MAX_PROVIDERS = 6
MAX_MODELS = 8

# "schema": ask for JSON that follows our schema (the provider enforces it where it can);
# "object": ask for a JSON object and put the schema in the prompt (the widely supported mode);
# "none": no response format at all, the prompt alone asks for JSON.
JsonMode = Literal["schema", "object", "none"]

_NAME_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,29}")
# Model ids such as "z-ai/glm-5.3-flash", "nvidia/nemotron-nano-3-30b-a3b:free", "@cf/meta/llama".
_MODEL_RE = re.compile(r"[A-Za-z0-9@][A-Za-z0-9._:/@+-]{0,119}")
_RESERVED_NAMES = frozenset({"gemini", "fake"})
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


class FallbackProvider(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    # Recorded with every result this provider writes, so the UI and the usage ledger say who did.
    name: str
    base_url: str
    api_key: SecretStr = Field(min_length=1)
    # In the order to try them. Each has its own allowance on most free tiers.
    models: tuple[str, ...] = Field(min_length=1, max_length=MAX_MODELS)
    # Reasoning models spend part of this on thinking before they answer, so it is generous.
    max_output_tokens: int = Field(default=16000, ge=512, le=65536)
    json_mode: JsonMode = "object"

    @field_validator("name")
    @classmethod
    def _check_name(cls, value: str) -> str:
        if not _NAME_RE.fullmatch(value) or value in _RESERVED_NAMES:
            raise ValueError(
                "must be 1-30 lowercase letters, digits, '-' or '_', and not 'gemini' or 'fake'"
            )
        return value

    @field_validator("base_url")
    @classmethod
    def _check_base_url(cls, value: str) -> str:
        parsed = urlparse(value.strip())
        host = parsed.hostname or ""
        local = host in _LOCAL_HOSTS
        if parsed.scheme not in {"http", "https"} or not host:
            raise ValueError("must be a URL like https://api.example.com/v1")
        if parsed.scheme == "http" and not local:
            raise ValueError("must use https (plain http is only allowed for a local server)")
        if parsed.query or parsed.fragment or parsed.username or parsed.password:
            raise ValueError("must not include credentials, a query or a fragment")
        return value.strip().rstrip("/")

    @field_validator("models")
    @classmethod
    def _check_models(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for name in value:
            if not _MODEL_RE.fullmatch(name):
                raise ValueError("each model must look like a model id, for example org/name")
        if len(set(value)) != len(value):
            raise ValueError("models must not repeat")
        return value


class FallbackConfigError(ValueError):
    """The value of ``LLM_FALLBACKS`` is not usable. The message never contains the value."""


def parse_fallbacks(raw: str) -> tuple[FallbackProvider, ...]:
    """The providers described by ``raw`` (a JSON list), or ``FallbackConfigError``."""
    try:
        data: object = json.loads(raw)
    except ValueError:
        raise FallbackConfigError("must be a JSON list, for example [{...}, {...}]") from None
    if not isinstance(data, list):
        raise FallbackConfigError("must be a JSON list, for example [{...}, {...}]")
    entries: list[object] = list(data)  # pyright: ignore[reportUnknownArgumentType]
    if len(entries) > MAX_PROVIDERS:
        raise FallbackConfigError(f"may list at most {MAX_PROVIDERS} providers")

    providers: list[FallbackProvider] = []
    for number, entry in enumerate(entries, start=1):
        try:
            providers.append(FallbackProvider.model_validate(entry))
        except ValidationError as exc:
            problems = "; ".join(
                f"{'.'.join(str(part) for part in error['loc']) or 'entry'}: {error['msg']}"
                for error in exc.errors(
                    include_input=False, include_url=False, include_context=False
                )
            )
            raise FallbackConfigError(f"provider {number}: {problems}") from None
    names = [provider.name for provider in providers]
    if len(set(names)) != len(names):
        raise FallbackConfigError("provider names must be different from each other")
    return tuple(providers)
