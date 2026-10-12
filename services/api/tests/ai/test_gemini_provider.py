"""The Gemini adapter, against a mock HTTP transport (no network, no real key)."""

import json
from collections.abc import Callable
from typing import Any

import httpx2
import pytest
from pydantic import BaseModel, Field, SecretStr

from app.ai.gemini import GeminiProvider
from app.ai.provider import (
    EmbeddingTask,
    LLMAuthError,
    LLMBlocked,
    LLMError,
    LLMInvalidOutput,
    LLMQuotaExhausted,
    LLMRateLimited,
    LLMRejected,
    LLMTimeout,
    LLMTruncated,
    LLMUnavailable,
    StructuredRequest,
)

pytestmark = pytest.mark.anyio

KEY = "test-key-not-a-real-secret-123"
URL = "https://gemini.test/v1beta/models/gemini-test:generateContent"

Handler = Callable[[httpx2.Request], httpx2.Response]


class Answer(BaseModel):
    name: str
    count: int = Field(ge=1)


REQUEST = StructuredRequest(
    system="You are a planner.",
    user="Plan something for <learner_data>{}</learner_data>",
    purpose="roadmap.plan",
    prompt_version="test/v1",
)


def make_provider(handler: Handler) -> GeminiProvider:
    return GeminiProvider(
        httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),
        api_key=SecretStr(KEY),
        model="gemini-test",
        base_url="https://gemini.test/v1beta/",
        max_output_tokens=1234,
        temperature=0.25,
        timeout_seconds=5,
        embedding_model="gemini-embedding-test",
    )


def answer_body(
    text: str | None = '{"name": "ok", "count": 2}',
    *,
    finish: str = "STOP",
    parts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    content_parts = parts if parts is not None else [{"text": text}]
    return {
        "candidates": [{"content": {"parts": content_parts}, "finishReason": finish}],
        "usageMetadata": {"promptTokenCount": 11, "candidatesTokenCount": 22},
        "modelVersion": "gemini-test-001",
    }


def respond(status: int, body: Any = None, headers: dict[str, str] | None = None) -> Handler:
    def handler(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(status, json=body, headers=headers)

    return handler


async def call(handler: Handler) -> Answer:
    result = await make_provider(handler).generate_structured(REQUEST, Answer)
    return result.value


# --- The request -----------------------------------------------------------------------------


async def test_the_request_has_the_shape_the_live_api_accepts() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json=answer_body())

    await make_provider(handler).generate_structured(REQUEST, Answer)

    (request,) = seen
    body = json.loads(request.content)
    assert request.method == "POST"
    assert str(request.url) == URL
    assert body["systemInstruction"] == {"parts": [{"text": "You are a planner."}]}
    assert body["contents"] == [{"role": "user", "parts": [{"text": REQUEST.user}]}]
    config = body["generationConfig"]
    assert config["maxOutputTokens"] == 1234
    assert config["temperature"] == 0.25
    # The two fields the live API accepts (the docs' "responseFormat" shape is rejected by it).
    assert config["responseMimeType"] == "application/json"
    assert "responseFormat" not in config
    schema = config["responseJsonSchema"]
    assert schema["properties"]["count"] == {"type": "integer", "minimum": 1}
    assert schema["required"] == ["name", "count"]


async def test_the_api_key_travels_in_a_header_and_never_in_the_url_or_body() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json=answer_body())

    await make_provider(handler).generate_structured(REQUEST, Answer)

    (request,) = seen
    assert request.headers["x-goog-api-key"] == KEY
    assert KEY not in str(request.url)
    assert KEY.encode() not in request.content


# --- A good answer ---------------------------------------------------------------------------


async def test_a_valid_answer_is_returned_with_usage_and_metadata() -> None:
    result = await make_provider(respond(200, answer_body())).generate_structured(REQUEST, Answer)

    assert result.value == Answer(name="ok", count=2)
    assert result.provider == "gemini"
    assert result.model_id == "gemini-test-001"
    assert (result.usage.input_tokens, result.usage.output_tokens) == (11, 22)
    assert result.finish_reason == "STOP"
    assert result.synthetic is False
    assert result.latency_ms >= 0


async def test_reasoning_parts_are_not_part_of_the_answer() -> None:
    body = answer_body(
        parts=[
            {"text": "Let me think about this...", "thought": True},
            {"text": '{"name": "ok",'},
            {"text": ' "count": 3}'},
        ]
    )

    assert await call(respond(200, body)) == Answer(name="ok", count=3)


async def test_missing_usage_is_tolerated() -> None:
    body = answer_body()
    del body["usageMetadata"]

    result = await make_provider(respond(200, body)).generate_structured(REQUEST, Answer)

    assert (result.usage.input_tokens, result.usage.output_tokens) == (None, None)


# --- HTTP failures ---------------------------------------------------------------------------


async def test_rate_limiting_is_retryable_and_carries_the_retry_after_hint() -> None:
    handler = respond(
        429, {"error": {"status": "RESOURCE_EXHAUSTED", "message": "quota"}}, {"retry-after": "7"}
    )

    with pytest.raises(LLMRateLimited) as caught:
        await call(handler)

    assert caught.value.retryable is True
    assert caught.value.retry_after == 7.0
    assert "RESOURCE_EXHAUSTED" in caught.value.detail


@pytest.mark.parametrize("status", [401, 403])
async def test_a_rejected_key_is_not_retryable(status: int) -> None:
    with pytest.raises(LLMAuthError) as caught:
        await call(respond(status, {"error": {"status": "PERMISSION_DENIED", "message": "denied"}}))

    assert caught.value.retryable is False


async def test_a_request_the_provider_refuses_is_not_retryable() -> None:
    with pytest.raises(LLMRejected) as caught:
        await call(respond(400, {"error": {"status": "INVALID_ARGUMENT", "message": "bad schema"}}))

    assert caught.value.retryable is False
    assert "bad schema" in caught.value.detail


@pytest.mark.parametrize("status", [500, 502, 503, 504])
async def test_server_errors_are_retryable(status: int) -> None:
    with pytest.raises(LLMUnavailable) as caught:
        await call(respond(status, {"error": {"message": "overloaded"}}))

    assert caught.value.retryable is True


async def test_a_timeout_is_retryable() -> None:
    def handler(_request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("slow")

    with pytest.raises(LLMTimeout) as caught:
        await call(handler)

    assert caught.value.retryable is True


async def test_a_connection_failure_is_retryable() -> None:
    def handler(_request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("no route to generativelanguage.googleapis.com")

    with pytest.raises(LLMUnavailable) as caught:
        await call(handler)

    assert caught.value.retryable is True
    assert "generativelanguage" not in caught.value.detail  # the host is not copied into errors


async def test_a_reply_that_is_not_json_is_an_outage_not_a_crash() -> None:
    def handler(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, text="<html>gateway</html>")

    with pytest.raises(LLMUnavailable):
        await call(handler)


# --- Unusable answers ------------------------------------------------------------------------


async def test_a_blocked_prompt_is_not_retryable() -> None:
    with pytest.raises(LLMBlocked) as caught:
        await call(respond(200, {"promptFeedback": {"blockReason": "SAFETY"}}))

    assert caught.value.retryable is False


@pytest.mark.parametrize("finish", ["SAFETY", "RECITATION", "PROHIBITED_CONTENT"])
async def test_an_answer_stopped_for_policy_is_blocked(finish: str) -> None:
    with pytest.raises(LLMBlocked):
        await call(respond(200, answer_body(finish=finish)))


async def test_a_cut_off_answer_is_reported_as_truncated() -> None:
    with pytest.raises(LLMTruncated) as caught:
        await call(respond(200, answer_body('{"name": "ok", "co', finish="MAX_TOKENS")))

    assert caught.value.retryable is True


@pytest.mark.parametrize(
    "body", [{"candidates": []}, {}, {"candidates": [{"finishReason": "OTHER"}]}]
)
async def test_a_reply_without_a_usable_candidate_is_an_outage(body: dict[str, Any]) -> None:
    with pytest.raises(LLMUnavailable):
        await call(respond(200, body))


async def test_an_empty_answer_is_invalid() -> None:
    with pytest.raises(LLMInvalidOutput):
        await call(respond(200, answer_body("   ")))


async def test_text_that_is_not_valid_json_is_invalid_output_and_is_not_echoed() -> None:
    with pytest.raises(LLMInvalidOutput) as caught:
        await call(respond(200, answer_body("Sure! Here is the plan: SECRET-MODEL-TEXT")))

    assert caught.value.problems
    assert "SECRET-MODEL-TEXT" not in repr(caught.value.problems) + caught.value.detail


async def test_json_that_breaks_the_schema_lists_the_fields_but_not_the_values() -> None:
    with pytest.raises(LLMInvalidOutput) as caught:
        await call(respond(200, answer_body('{"name": "ok", "count": 0}')))

    assert caught.value.retryable is False
    assert any(problem.startswith("count:") for problem in caught.value.problems)


async def test_a_missing_field_is_named() -> None:
    with pytest.raises(LLMInvalidOutput) as caught:
        await call(respond(200, answer_body('{"count": 2}')))

    assert any(problem.startswith("name:") for problem in caught.value.problems)


# --- Secrets ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "handler",
    [
        respond(401, {"error": {"status": "UNAUTHENTICATED", "message": "API key not valid"}}),
        respond(429, {"error": {"message": "quota"}}),
        respond(500, {"error": {"message": "boom"}}),
        respond(200, answer_body("not json")),
    ],
)
async def test_no_error_ever_contains_the_api_key(handler: Handler) -> None:
    with pytest.raises(LLMError) as caught:
        await call(handler)

    assert KEY not in repr(caught.value)
    assert KEY not in caught.value.detail
    assert KEY not in caught.value.user_message


# --- Allowances, retry hints and falling back to another model -------------------------------


def quota_error(*, daily: bool, delay: str = "31s") -> dict[str, Any]:
    """The shape of Google's 429 (observed live): which quota ran out, and when to try again."""
    quota_id = (
        "GenerateRequestsPerDayPerProjectPerModel-FreeTier"
        if daily
        else "GenerateRequestsPerMinutePerProjectPerModel-FreeTier"
    )
    return {
        "error": {
            "code": 429,
            "status": "RESOURCE_EXHAUSTED",
            "message": "You exceeded your current quota. A long message with the plan name.",
            "details": [
                {
                    "@type": "type.googleapis.com/google.rpc.QuotaFailure",
                    "violations": [{"quotaId": quota_id, "quotaValue": "20"}],
                },
                {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": delay},
            ],
        }
    }


async def test_a_daily_allowance_is_its_own_error_with_the_time_until_it_resets() -> None:
    handler = respond(429, quota_error(daily=True, delay="67881s"))

    with pytest.raises(LLMQuotaExhausted) as caught:
        await call(handler)

    assert caught.value.retryable is False  # waiting minutes cannot help
    assert caught.value.code == "AI_QUOTA_EXHAUSTED"
    assert caught.value.retry_after == 67881.0
    assert "resets in about 19 hours" in caught.value.user_message


async def test_a_per_minute_limit_uses_googles_own_retry_delay() -> None:
    handler = respond(429, quota_error(daily=False, delay="31s"))

    with pytest.raises(LLMRateLimited) as caught:
        await call(handler)

    assert caught.value.retryable is True and caught.value.retry_after == 31.0
    assert not isinstance(caught.value, LLMQuotaExhausted)


def provider_with_models(handler: Handler, *models: str) -> GeminiProvider:
    return GeminiProvider(
        httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),
        api_key=SecretStr(KEY),
        model=models[0],
        fallback_models=models[1:],
        base_url="https://gemini.test/v1beta/",
        max_output_tokens=1234,
        temperature=0.25,
        timeout_seconds=5,
        embedding_model="gemini-embedding-test",
    )


def model_of(request: httpx2.Request) -> str:
    return request.url.path.rsplit("/", 1)[-1].split(":")[0]


async def test_when_a_models_allowance_is_used_up_the_next_model_answers() -> None:
    asked: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        asked.append(model_of(request))
        if model_of(request) == "model-a":
            return httpx2.Response(429, json=quota_error(daily=True, delay="3600s"))
        return httpx2.Response(200, json={**answer_body(), "modelVersion": ""})

    provider = provider_with_models(handler, "model-a", "model-b", "model-c")

    first = await provider.generate_structured(REQUEST, Answer)
    second = await provider.generate_structured(REQUEST, Answer)

    assert first.value == Answer(name="ok", count=2)
    assert first.model_id == "model-b" and second.model_id == "model-b"
    # The exhausted model was tried once, then left alone until its allowance returns.
    assert asked == ["model-a", "model-b", "model-b"]


async def test_an_overloaded_model_is_skipped_for_a_while_too() -> None:
    asked: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        asked.append(model_of(request))
        if model_of(request) == "model-a":
            return httpx2.Response(
                503, json={"error": {"status": "UNAVAILABLE", "message": "high demand"}}
            )
        return httpx2.Response(200, json=answer_body())

    provider = provider_with_models(handler, "model-a", "model-b")

    await provider.generate_structured(REQUEST, Answer)
    await provider.generate_structured(REQUEST, Answer)

    assert asked == ["model-a", "model-b", "model-b"]


async def test_when_every_model_is_used_up_the_error_says_when_the_soonest_comes_back() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        delay = "7200s" if model_of(request) == "model-a" else "3600s"
        return httpx2.Response(429, json=quota_error(daily=True, delay=delay))

    provider = provider_with_models(handler, "model-a", "model-b")

    with pytest.raises(LLMQuotaExhausted) as first:
        await provider.generate_structured(REQUEST, Answer)
    with pytest.raises(LLMQuotaExhausted) as again:  # both are benched now: no more requests
        await provider.generate_structured(REQUEST, Answer)

    assert first.value.retry_after == 3600.0 and "about 1 hour." in first.value.user_message
    assert again.value.retry_after is not None and again.value.retry_after <= 3600.0


async def test_a_rejected_key_does_not_try_the_other_models() -> None:
    asked: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        asked.append(model_of(request))
        return httpx2.Response(403, json={"error": {"status": "PERMISSION_DENIED"}})

    provider = provider_with_models(handler, "model-a", "model-b")

    with pytest.raises(LLMAuthError):
        await provider.generate_structured(REQUEST, Answer)

    assert asked == ["model-a"]


async def test_embeddings_use_their_own_model_whatever_the_generation_models_do() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        if "batchEmbedContents" in request.url.path:
            return httpx2.Response(429, json=quota_error(daily=False, delay="12s"))
        return httpx2.Response(200, json=answer_body())

    provider = provider_with_models(handler, "model-a", "model-b")

    with pytest.raises(LLMRateLimited) as caught:
        await provider.embed(["a passage"], EmbeddingTask.DOCUMENT)

    assert caught.value.retry_after == 12.0


# --- Thinking level ---------------------------------------------------------------------------


def provider_thinking(handler: Handler, level: str | None) -> GeminiProvider:
    return GeminiProvider(
        httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),
        api_key=SecretStr(KEY),
        model="model-a",
        base_url="https://gemini.test/v1beta/",
        max_output_tokens=1234,
        temperature=0.25,
        timeout_seconds=5,
        embedding_model="gemini-embedding-test",
        thinking_level=level,
    )


async def test_the_thinking_level_is_sent_when_one_is_configured() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(json.loads(request.content)["generationConfig"])
        return httpx2.Response(200, json=answer_body())

    await provider_thinking(handler, "low").generate_structured(REQUEST, Answer)
    await provider_thinking(handler, None).generate_structured(REQUEST, Answer)

    assert seen[0]["thinkingConfig"] == {"thinkingLevel": "low"}
    assert "thinkingConfig" not in seen[1]
    assert seen[0]["maxOutputTokens"] == 1234  # the rest of the configuration is untouched


async def test_a_model_that_refuses_the_level_is_asked_again_without_it_and_remembered() -> None:
    seen: list[bool] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        has_level = "thinkingConfig" in json.loads(request.content)["generationConfig"]
        seen.append(has_level)
        if has_level:
            return httpx2.Response(
                400,
                json={
                    "error": {
                        "status": "INVALID_ARGUMENT",
                        "message": "Thinking level LOW is not supported for this model.",
                    }
                },
            )
        return httpx2.Response(200, json=answer_body())

    provider = provider_thinking(handler, "low")

    first = await provider.generate_structured(REQUEST, Answer)
    second = await provider.generate_structured(REQUEST, Answer)

    assert first.value == second.value == Answer(name="ok", count=2)
    assert seen == [True, False, False]  # tried once, then never again for this model


async def test_an_unrelated_rejection_is_not_mistaken_for_a_thinking_problem() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            400, json={"error": {"status": "INVALID_ARGUMENT", "message": "Bad schema."}}
        )

    with pytest.raises(LLMRejected):
        await provider_thinking(handler, "low").generate_structured(REQUEST, Answer)
