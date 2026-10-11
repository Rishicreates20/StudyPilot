"""Google Gemini over its REST API (``models.generateContent``).

Written against Google's published reference, checked 2026-10-11:

* ``POST {base}/models/{model}:generateContent`` with the key in the ``x-goog-api-key`` header
  (never in the URL, so it cannot end up in a log line);
* structured output is requested with ``generationConfig.responseFormat.text`` =
  ``{"mimeType": "application/json", "schema": {...}}``;
* the answer is ``candidates[0].content.parts[*].text`` and token counts are in ``usageMetadata``.

No SDK is used: the REST surface is small, stable and easy to test with a mock transport, and it
avoids a dependency that Windows' Smart App Control could block. The reply is always validated
against the caller's Pydantic model, so a surprising answer becomes a typed error, never data.
"""

import time
from typing import Any, cast

import httpx2
import structlog
from pydantic import BaseModel, SecretStr, ValidationError

from app.ai.provider import (
    LLMAuthError,
    LLMBlocked,
    LLMInvalidOutput,
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

log = structlog.get_logger("app.ai.gemini")

_BLOCKING_FINISH_REASONS = frozenset(
    {"SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII", "LANGUAGE"}
)
_MAX_DETAIL_CHARS = 300
_MAX_PROBLEMS = 20


class GeminiProvider:
    name = "gemini"

    def __init__(
        self,
        client: httpx2.AsyncClient,
        *,
        api_key: SecretStr,
        model: str,
        base_url: str,
        max_output_tokens: int,
        temperature: float,
        timeout_seconds: float,
    ) -> None:
        self._client = client
        self._api_key = api_key
        self._model = model
        self._url = f"{base_url.rstrip('/')}/models/{model}:generateContent"
        self._max_output_tokens = max_output_tokens
        self._temperature = temperature
        self._timeout = timeout_seconds

    async def generate_structured[T: BaseModel](
        self, request: StructuredRequest, schema: type[T]
    ) -> StructuredResult[T]:
        body = {
            "systemInstruction": {"parts": [{"text": request.system}]},
            "contents": [{"role": "user", "parts": [{"text": request.user}]}],
            "generationConfig": {
                "temperature": self._temperature,
                "maxOutputTokens": self._max_output_tokens,
                "responseFormat": {
                    "text": {"mimeType": "application/json", "schema": provider_schema(schema)}
                },
            },
        }
        started = time.monotonic()
        response = await self._post(body)
        latency_ms = round((time.monotonic() - started) * 1000)
        payload = self._payload(response)
        text, finish_reason = self._text_and_finish_reason(payload)
        value = self._parse(text, schema)
        usage_metadata = _dict(payload.get("usageMetadata"))
        return StructuredResult(
            value=value,
            provider=self.name,
            model_id=str(payload.get("modelVersion") or self._model),
            usage=Usage(
                input_tokens=_as_int(usage_metadata.get("promptTokenCount")),
                output_tokens=_as_int(usage_metadata.get("candidatesTokenCount")),
            ),
            latency_ms=latency_ms,
            finish_reason=finish_reason,
        )

    async def _post(self, body: dict[str, Any]) -> httpx2.Response:
        try:
            response = await self._client.post(
                self._url,
                json=body,
                headers={"x-goog-api-key": self._api_key.get_secret_value()},
                timeout=self._timeout,
            )
        except httpx2.TimeoutException:
            raise LLMTimeout("request timed out") from None
        except httpx2.TransportError as exc:
            # The exception type is enough to diagnose; its message can include the host.
            raise LLMUnavailable(f"transport error: {type(exc).__name__}") from None
        if response.is_success:
            return response
        self._raise_for_status(response)
        raise AssertionError("unreachable")  # pragma: no cover

    @staticmethod
    def _raise_for_status(response: httpx2.Response) -> None:
        detail = _error_detail(response)
        status = response.status_code
        if status == 429:
            raise LLMRateLimited(detail, retry_after=_retry_after(response))
        if status in {401, 403}:
            raise LLMAuthError(detail)
        if status == 408:
            raise LLMTimeout(detail)
        if status >= 500:
            raise LLMUnavailable(detail)
        raise LLMRejected(detail)

    @staticmethod
    def _payload(response: httpx2.Response) -> dict[str, Any]:
        try:
            payload: object = response.json()
        except ValueError:
            raise LLMUnavailable("the provider's reply was not JSON") from None
        if not isinstance(payload, dict):
            raise LLMUnavailable("the provider's reply was not a JSON object")
        return cast(dict[str, Any], payload)

    @staticmethod
    def _text_and_finish_reason(payload: dict[str, Any]) -> tuple[str, str]:
        feedback = _dict(payload.get("promptFeedback"))
        if feedback.get("blockReason"):
            raise LLMBlocked(f"prompt blocked: {feedback['blockReason']}")

        candidates = _list(payload.get("candidates"))
        if not candidates:
            raise LLMUnavailable("the provider returned no candidates")
        candidate = _dict(candidates[0])
        finish_reason = str(candidate.get("finishReason") or "STOP")
        if finish_reason == "MAX_TOKENS":
            raise LLMTruncated("finishReason=MAX_TOKENS")
        if finish_reason in _BLOCKING_FINISH_REASONS:
            raise LLMBlocked(f"finishReason={finish_reason}")
        if finish_reason != "STOP":
            raise LLMUnavailable(f"finishReason={finish_reason}")

        parts = [_dict(part) for part in _list(_dict(candidate.get("content")).get("parts"))]
        # "Thought" parts are the model's reasoning summaries, not part of the answer.
        text = "".join(
            str(part["text"]) for part in parts if "text" in part and not part.get("thought")
        )
        if not text.strip():
            raise LLMInvalidOutput("the provider returned an empty answer")
        return text, finish_reason

    @staticmethod
    def _parse[T: BaseModel](text: str, schema: type[T]) -> T:
        try:
            return schema.model_validate_json(text)
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
    """``value`` if it is a JSON object, otherwise an empty one."""
    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


def _list(value: object) -> list[Any]:
    """``value`` if it is a JSON array, otherwise an empty one."""
    return cast(list[Any], value) if isinstance(value, list) else []


def _as_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _retry_after(response: httpx2.Response) -> float | None:
    try:
        return max(0.0, float(response.headers.get("retry-after", "")))
    except ValueError:
        return None


def _error_detail(response: httpx2.Response) -> str:
    """``HTTP 400 INVALID_ARGUMENT: <message>``, shortened. For server logs only."""
    status = f"HTTP {response.status_code}"
    try:
        body: object = response.json()
    except ValueError:
        return status
    error = _dict(_dict(body).get("error"))
    pieces = [
        status,
        str(error.get("status") or "").strip(),
        str(error.get("message") or "").strip(),
    ]
    return ": ".join(piece for piece in pieces if piece)[:_MAX_DETAIL_CHARS]
