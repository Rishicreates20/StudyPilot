"""Any provider that speaks the OpenAI chat format (``POST {base}/chat/completions``).

Groq, Mistral, Cerebras, NVIDIA NIM, OpenRouter, Cloudflare, GitHub Models, a local Ollama and many
more offer free tiers behind this one shape, so a single adapter reaches all of them. It only
*generates* structured output: embeddings and reading pictures stay with the main provider (see
``app.ai.chain``), because every vector in the database must come from one recorded model.

Providers differ in how well they enforce a response format, so the adapter asks for the most
specific one the provider is configured for and steps down (schema, then JSON object, then plain
prompt) when a provider rejects it, remembering that per model. Whatever comes back is cut down
to its JSON object (reasoning blocks and code fences removed) and validated against the caller's
Pydantic model, so a surprising answer becomes a typed error, never data.

The key travels only in the ``Authorization`` header. Prompts, answers and keys are never logged,
and an error's ``detail`` (for server logs) is the provider's own short message, nothing of ours.
"""

import json
import re
import time
from collections.abc import Callable, Sequence
from typing import Any, cast

import httpx2
import structlog
from pydantic import BaseModel, SecretStr, ValidationError

from app.ai.bench import Bench
from app.ai.fallback_config import JsonMode
from app.ai.provider import (
    LLMAuthError,
    LLMBlocked,
    LLMInvalidOutput,
    LLMQuotaExhausted,
    LLMRateLimited,
    LLMRejected,
    LLMTimeout,
    LLMTruncated,
    LLMUnavailable,
    StructuredRequest,
    StructuredResult,
    Usage,
)
from app.ai.schema_utils import provider_schema

log = structlog.get_logger("app.ai.openai_compat")

_MAX_DETAIL_CHARS = 300
_MAX_PROBLEMS = 20
_MAX_MODEL_ID_CHARS = 100
# A daily allowance, as providers phrase it ("free-models-per-day", "requests per day", "RPD").
_DAILY_RE = re.compile(r"per[ -]day|daily|\brpd\b|\btpd\b|insufficient_quota|exceeded your current")
# "Please try again in 7m12.5s" / "in 2h3m" / "in 30s".
_RETRY_IN_RE = re.compile(r"try again in\s+((?:\d+(?:\.\d+)?[hms]\s*)+)", re.IGNORECASE)
_DURATION_PART_RE = re.compile(r"(\d+(?:\.\d+)?)([hms])")
_THINK_RE = re.compile(r"<think(?:ing)?>.*?</think(?:ing)?>", re.DOTALL | re.IGNORECASE)
_FENCE_RE = re.compile(r"^```[A-Za-z0-9_-]*\s*\n?|\n?```\s*$")
_FORMAT_WORDS = ("response_format", "json_schema", "json_object", "structured", "guided_json")

_ANSWER_FORMAT = """

ANSWER FORMAT
Reply with exactly one JSON object and nothing else: no markdown, no code fence, no commentary \
before or after it. It must follow this JSON Schema (all required fields present, no extra ones):
"""


class OpenAICompatibleProvider:
    """Generation only. ``name`` is recorded with every result this provider writes."""

    def __init__(
        self,
        client: httpx2.AsyncClient,
        *,
        name: str,
        base_url: str,
        api_key: SecretStr,
        models: Sequence[str],
        max_output_tokens: int,
        temperature: float,
        timeout_seconds: float,
        json_mode: JsonMode = "object",
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.name = name
        self._client = client
        self._api_key = api_key
        self._url = f"{base_url.rstrip('/')}/chat/completions"
        self._models = tuple(dict.fromkeys(models))
        self._max_output_tokens = max_output_tokens
        self._temperature = temperature
        self._timeout = timeout_seconds
        self._json_mode: JsonMode = json_mode
        # Models that rejected the response format asked for: the format each now gets.
        self._mode: dict[str, JsonMode] = {}
        self._bench = Bench(f"{name}-models", clock=clock)

    async def generate_structured[T: BaseModel](
        self, request: StructuredRequest, schema: type[T]
    ) -> StructuredResult[T]:
        """Ask the first model that can answer; a typed ``LLMError`` if none can."""
        started = time.monotonic()

        async def ask(model: str) -> tuple[T, dict[str, Any], str]:
            return await self._ask(model, request, schema)

        (value, payload, finish_reason), used = await self._bench.first_answer(self._models, ask)
        usage = _dict(payload.get("usage"))
        return StructuredResult(
            value=value,
            provider=self.name,
            model_id=str(payload.get("model") or used)[:_MAX_MODEL_ID_CHARS],
            usage=Usage(
                input_tokens=_as_int(usage.get("prompt_tokens")),
                output_tokens=_as_int(usage.get("completion_tokens")),
            ),
            latency_ms=round((time.monotonic() - started) * 1000),
            finish_reason=finish_reason,
        )

    async def _ask[T: BaseModel](
        self, model: str, request: StructuredRequest, schema: type[T]
    ) -> tuple[T, dict[str, Any], str]:
        mode: JsonMode = self._mode.get(model) or self._json_mode
        while True:
            try:
                response = await self._post(self._body(model, request, schema, mode))
                break
            except LLMRejected as exc:
                lower = _step_down(mode, exc.detail)
                if lower is None:
                    raise
                log.warning("openai_compat.format_refused", provider=self.name, model=model)
                mode = lower
                self._mode[model] = lower
        payload = _payload(response)
        text, finish_reason = _text_and_finish_reason(payload)
        return _parse(text, schema), payload, finish_reason

    def _body(
        self, model: str, request: StructuredRequest, schema: type[BaseModel], mode: JsonMode
    ) -> dict[str, Any]:
        reduced = provider_schema(schema)
        system = request.system
        if mode != "schema":
            system += _ANSWER_FORMAT + json.dumps(reduced, separators=(",", ":"))
        body: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": request.user},
            ],
            "temperature": self._temperature,
            "max_tokens": self._max_output_tokens,
            "stream": False,
        }
        if mode == "schema":
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "answer", "schema": reduced, "strict": False},
            }
        elif mode == "object":
            body["response_format"] = {"type": "json_object"}
        return body

    async def _post(self, body: dict[str, Any]) -> httpx2.Response:
        try:
            response = await self._client.post(
                self._url,
                json=body,
                headers={"Authorization": f"Bearer {self._api_key.get_secret_value()}"},
                timeout=self._timeout,
            )
        except httpx2.TimeoutException:
            raise LLMTimeout("request timed out") from None
        except httpx2.TransportError as exc:
            # The exception type is enough to diagnose; its message can include the host.
            raise LLMUnavailable(f"transport error: {type(exc).__name__}") from None
        if response.is_success:
            return response
        _raise_for_status(response)
        raise AssertionError("unreachable")  # pragma: no cover


def _raise_for_status(response: httpx2.Response) -> None:
    detail = _error_detail(response)
    status = response.status_code
    delay = _retry_delay(response, detail)
    if status == 429:
        if _DAILY_RE.search(detail.casefold()):
            raise LLMQuotaExhausted(detail, retry_after=delay)
        raise LLMRateLimited(detail, retry_after=delay)
    if status == 402:  # out of credits
        raise LLMQuotaExhausted(detail, retry_after=delay)
    if status in {401, 403}:
        raise LLMAuthError(detail)
    if status == 408:
        raise LLMTimeout(detail)
    if status >= 500:
        raise LLMUnavailable(detail, retry_after=delay)
    raise LLMRejected(detail)


def _error_message(body: object) -> tuple[str, str]:
    """``(code or type, message)`` from the several error shapes providers use."""
    data = _dict(body)
    error = data.get("error")
    if isinstance(error, str):
        return "", error
    fields = _dict(error) or data
    label = str(fields.get("code") or fields.get("type") or fields.get("status") or "")
    message = str(fields.get("message") or fields.get("detail") or fields.get("title") or "")
    return label, message


def _error_detail(response: httpx2.Response) -> str:
    """``HTTP 429 rate_limit_exceeded: <message>``, shortened. For server logs only."""
    status = f"HTTP {response.status_code}"
    try:
        body: object = response.json()
    except ValueError:
        return status
    label, message = _error_message(body)
    pieces = [status, label.strip(), " ".join(message.split())]
    return ": ".join(piece for piece in pieces if piece)[:_MAX_DETAIL_CHARS]


def _retry_delay(response: httpx2.Response, detail: str) -> float | None:
    """How long the provider says to wait: ``Retry-After``, or "try again in 7m12s" in the text."""
    try:
        return max(0.0, float(response.headers.get("retry-after", "")))
    except ValueError:
        pass
    found = _RETRY_IN_RE.search(detail)
    if found is None:
        return None
    seconds = 0.0
    for amount, unit in _DURATION_PART_RE.findall(found.group(1).lower()):
        seconds += float(amount) * {"h": 3600.0, "m": 60.0, "s": 1.0}[unit]
    return seconds or None


def _step_down(mode: JsonMode, detail: str) -> JsonMode | None:
    """The next less demanding response format, if ``detail`` says the format was the problem."""
    if mode == "none" or not any(word in detail.casefold() for word in _FORMAT_WORDS):
        return None
    return "object" if mode == "schema" else "none"


def _payload(response: httpx2.Response) -> dict[str, Any]:
    try:
        payload: object = response.json()
    except ValueError:
        raise LLMUnavailable("the provider's reply was not JSON") from None
    data = _dict(payload)
    if not data:
        raise LLMUnavailable("the provider's reply was not a JSON object")
    if "choices" not in data and "error" in data:
        # Some gateways answer 200 with the failure in the body.
        label, message = _error_message(data)
        raise LLMUnavailable(
            f"provider error in a 200 reply: {label} {message}"[:_MAX_DETAIL_CHARS]
        )
    return data


def _text_and_finish_reason(payload: dict[str, Any]) -> tuple[str, str]:
    choices = _list(payload.get("choices"))
    if not choices:
        raise LLMUnavailable("the provider returned no choices")
    choice = _dict(choices[0])
    finish_reason = str(choice.get("finish_reason") or "stop")
    if finish_reason == "content_filter":
        raise LLMBlocked("finish_reason=content_filter")
    content = _dict(choice.get("message")).get("content")
    if isinstance(content, list):  # some providers return a list of content parts
        text = "".join(str(_dict(part).get("text", "")) for part in cast(list[Any], content))
    else:
        text = content if isinstance(content, str) else ""
    if finish_reason == "length":
        raise LLMTruncated("finish_reason=length")
    if not text.strip():
        raise LLMInvalidOutput("the provider returned an empty answer")
    return text, finish_reason


def extract_json(text: str) -> str:
    """The JSON object inside a model's reply: no reasoning blocks, fences or surrounding prose."""
    cleaned = _THINK_RE.sub("", text).strip()
    cleaned = _FENCE_RE.sub("", cleaned).strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    return cleaned[start : end + 1] if 0 <= start < end else cleaned


def _parse[T: BaseModel](text: str, schema: type[T]) -> T:
    try:
        return schema.model_validate_json(extract_json(text))
    except ValidationError as exc:
        # Locations and rules only: the model's own text is never copied into an error.
        problems = [
            f"{'.'.join(str(part) for part in error['loc']) or 'answer'}: {error['msg']}"
            for error in exc.errors(include_input=False, include_url=False)
        ][:_MAX_PROBLEMS]
        raise LLMInvalidOutput(
            f"the answer did not match the schema ({len(exc.errors())} problems)",
            problems=problems,
        ) from None


def _dict(value: object) -> dict[str, Any]:
    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


def _list(value: object) -> list[Any]:
    return cast(list[Any], value) if isinstance(value, list) else []


def _as_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None
