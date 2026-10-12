"""The OpenAI-compatible adapter, against a mock HTTP transport (no network, no real key)."""

import json
from collections.abc import Callable
from typing import Any

import httpx2
import pytest
from pydantic import BaseModel, Field, SecretStr

from app.ai.fallback_config import JsonMode
from app.ai.openai_compat import OpenAICompatibleProvider, extract_json
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
)

pytestmark = pytest.mark.anyio

KEY = "test-key-not-a-real-secret-123"
URL = "https://llm.test/v1/chat/completions"

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


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def make_provider(
    handler: Handler,
    *,
    models: tuple[str, ...] = ("model-a",),
    json_mode: JsonMode = "object",
    clock: Clock | None = None,
) -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(
        httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),
        name="freeco",
        base_url="https://llm.test/v1/",
        api_key=SecretStr(KEY),
        models=models,
        max_output_tokens=1234,
        temperature=0.25,
        timeout_seconds=5,
        json_mode=json_mode,
        clock=clock or Clock(),
    )


def completion(
    content: Any = '{"name": "ok", "count": 2}',
    *,
    finish: str = "stop",
    model: str = "served-model-001",
) -> dict[str, Any]:
    return {
        "model": model,
        "choices": [
            {"message": {"role": "assistant", "content": content}, "finish_reason": finish}
        ],
        "usage": {"prompt_tokens": 11, "completion_tokens": 22},
    }


def respond(status: int, body: Any = None, headers: dict[str, str] | None = None) -> Handler:
    def handler(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(status, json=body, headers=headers)

    return handler


async def call(handler: Handler, **options: Any) -> Answer:
    result = await make_provider(handler, **options).generate_structured(REQUEST, Answer)
    return result.value


# --- The request -----------------------------------------------------------------------------


async def test_the_request_is_a_standard_chat_completion_asking_for_a_json_object() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json=completion())

    await make_provider(handler).generate_structured(REQUEST, Answer)

    (request,) = seen
    body = json.loads(request.content)
    assert request.method == "POST"
    assert str(request.url) == URL
    assert body["model"] == "model-a"
    system, user = body["messages"]
    assert system["role"] == "system" and system["content"].startswith("You are a planner.")
    assert user == {"role": "user", "content": REQUEST.user}
    assert (body["temperature"], body["max_tokens"], body["stream"]) == (0.25, 1234, False)
    assert body["response_format"] == {"type": "json_object"}


async def test_the_schema_is_put_in_the_prompt_when_the_provider_does_not_enforce_one() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(json.loads(request.content))
        return httpx2.Response(200, json=completion())

    await make_provider(handler).generate_structured(REQUEST, Answer)

    system = seen[0]["messages"][0]["content"]
    assert "ANSWER FORMAT" in system and '"count"' in system and '"required"' in system


async def test_schema_mode_sends_the_schema_as_the_response_format_instead() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(json.loads(request.content))
        return httpx2.Response(200, json=completion())

    await make_provider(handler, json_mode="schema").generate_structured(REQUEST, Answer)

    body = seen[0]
    assert body["messages"][0]["content"] == "You are a planner."
    spec = body["response_format"]["json_schema"]
    assert body["response_format"]["type"] == "json_schema"
    assert spec["strict"] is False and spec["schema"]["properties"]["count"]["minimum"] == 1


async def test_none_mode_sends_no_response_format_but_still_asks_for_json_in_the_prompt() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(json.loads(request.content))
        return httpx2.Response(200, json=completion())

    await make_provider(handler, json_mode="none").generate_structured(REQUEST, Answer)

    assert "response_format" not in seen[0]
    assert "ANSWER FORMAT" in seen[0]["messages"][0]["content"]


async def test_the_api_key_travels_in_a_header_and_never_in_the_url_or_body() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json=completion())

    await make_provider(handler).generate_structured(REQUEST, Answer)

    (request,) = seen
    assert request.headers["authorization"] == f"Bearer {KEY}"
    assert KEY not in str(request.url)
    assert KEY.encode() not in request.content


# --- A good answer ---------------------------------------------------------------------------


async def test_a_valid_answer_is_returned_with_usage_and_who_answered() -> None:
    result = await make_provider(respond(200, completion())).generate_structured(REQUEST, Answer)

    assert result.value == Answer(name="ok", count=2)
    assert result.provider == "freeco"
    assert result.model_id == "served-model-001"
    assert (result.usage.input_tokens, result.usage.output_tokens) == (11, 22)
    assert result.finish_reason == "stop" and result.latency_ms >= 0
    assert result.synthetic is False


async def test_the_model_id_falls_back_to_the_requested_one_and_is_never_too_long() -> None:
    body = completion()
    del body["model"]
    named = await make_provider(respond(200, body)).generate_structured(REQUEST, Answer)
    long = await make_provider(respond(200, completion(model="m" * 300))).generate_structured(
        REQUEST, Answer
    )

    assert named.model_id == "model-a"
    assert len(long.model_id) == 100


@pytest.mark.parametrize(
    "content",
    [
        '```json\n{"name": "ok", "count": 2}\n```',
        '```\n{"name": "ok", "count": 2}\n```',
        '<think>I should say 3, no, 2.</think>\n{"name": "ok", "count": 2}',
        '<thinking>{"name": "decoy", "count": 9}</thinking>{"name": "ok", "count": 2}',
        'Here is the plan:\n{"name": "ok", "count": 2}\nHope that helps!',
        [{"type": "text", "text": '{"name": "ok", '}, {"type": "text", "text": '"count": 2}'}],
    ],
)
async def test_the_json_object_is_found_inside_the_ways_models_wrap_it(content: Any) -> None:
    assert await call(respond(200, completion(content))) == Answer(name="ok", count=2)


def test_extract_json_leaves_text_without_an_object_alone() -> None:
    assert extract_json("no braces here") == "no braces here"


# --- A bad answer ----------------------------------------------------------------------------


async def test_an_answer_that_does_not_match_the_schema_is_invalid_and_never_quoted() -> None:
    private_text = "the learner's private essay about their diagnosis"
    handler = respond(200, completion(json.dumps({"name": private_text, "count": 0})))

    with pytest.raises(LLMInvalidOutput) as raised:
        await call(handler)

    assert any(problem.startswith("count:") for problem in raised.value.problems)
    assert private_text not in str(raised.value) and private_text not in " ".join(
        raised.value.problems
    )


async def test_text_that_is_not_json_is_invalid_output() -> None:
    with pytest.raises(LLMInvalidOutput):
        await call(respond(200, completion("I cannot help with that.")))


async def test_an_empty_answer_is_invalid_output() -> None:
    with pytest.raises(LLMInvalidOutput):
        await call(respond(200, completion("   ")))


async def test_an_answer_cut_off_at_the_token_limit_is_truncated_even_if_it_has_text() -> None:
    with pytest.raises(LLMTruncated):
        await call(respond(200, completion('{"name": "ok", "co', finish="length")))


async def test_a_reasoning_model_that_used_everything_on_thinking_is_truncated() -> None:
    with pytest.raises(LLMTruncated):
        await call(respond(200, completion("", finish="length")))


async def test_a_content_filter_is_blocked() -> None:
    with pytest.raises(LLMBlocked):
        await call(respond(200, completion("", finish="content_filter")))


async def test_a_reply_without_choices_is_unavailable() -> None:
    with pytest.raises(LLMUnavailable):
        await call(respond(200, {"choices": []}))


async def test_an_error_inside_a_200_reply_is_unavailable_not_an_answer() -> None:
    body = {"error": {"code": 502, "message": "upstream provider crashed"}}

    with pytest.raises(LLMUnavailable):
        await call(respond(200, body))


async def test_a_reply_that_is_not_json_is_unavailable() -> None:
    def handler(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, text="<html>gateway</html>")

    with pytest.raises(LLMUnavailable):
        await call(handler)


# --- Failures --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (401, {"error": {"message": "Invalid API key"}}, LLMAuthError),
        (403, {"error": {"message": "model not allowed"}}, LLMAuthError),
        (402, {"error": {"code": 402, "message": "Insufficient credits"}}, LLMQuotaExhausted),
        (408, None, LLMTimeout),
        (500, {"error": {"message": "boom"}}, LLMUnavailable),
        (503, {"detail": "overloaded"}, LLMUnavailable),
        (400, {"error": {"message": "max_tokens is too large"}}, LLMRejected),
        (404, {"error": {"message": "The model does not exist"}}, LLMRejected),
        (429, {"error": {"message": "Too many requests, slow down"}}, LLMRateLimited),
        (
            429,
            {"error": {"type": "insufficient_quota", "message": "You exceeded your current quota"}},
            LLMQuotaExhausted,
        ),
        (
            429,
            {"error": {"code": 429, "message": "Rate limit exceeded: free-models-per-day"}},
            LLMQuotaExhausted,
        ),
        (
            429,
            {"error": {"message": "Rate limit reached on tokens per day (TPD): Limit 100000"}},
            LLMQuotaExhausted,
        ),
    ],
)
async def test_each_failure_becomes_the_typed_error_the_job_queue_understands(
    status: int, body: Any, expected: type[Exception]
) -> None:
    with pytest.raises(expected):
        await call(respond(status, body))


async def test_retry_after_is_passed_on_in_seconds() -> None:
    handler = respond(429, {"error": {"message": "slow down"}}, headers={"retry-after": "17"})

    with pytest.raises(LLMRateLimited) as raised:
        await call(handler)

    assert raised.value.retry_after == 17


@pytest.mark.parametrize(
    ("message", "seconds"),
    [
        ("Rate limit reached. Please try again in 7m12.5s.", 432.5),
        ("Limit reached, try again in 2h3m", 7380),
        ("Please try again in 30s", 30),
    ],
)
async def test_a_wait_stated_in_the_message_is_understood(message: str, seconds: float) -> None:
    with pytest.raises(LLMRateLimited) as raised:
        await call(respond(429, {"error": {"message": message}}))

    assert raised.value.retry_after == pytest.approx(seconds)


async def test_the_error_detail_is_the_providers_short_message_and_never_contains_the_key() -> None:
    body = {"error": {"code": "rate_limit_exceeded", "message": "slow   down\nplease"}}

    with pytest.raises(LLMRateLimited) as raised:
        await call(respond(429, body))

    assert raised.value.detail == "HTTP 429: rate_limit_exceeded: slow down please"
    assert KEY not in raised.value.detail


async def test_the_user_never_sees_the_providers_words() -> None:
    body = {"error": {"message": "Your prompt mentioned a private diagnosis"}}

    with pytest.raises(LLMRejected) as raised:
        await call(respond(400, body))

    assert "diagnosis" not in raised.value.user_message


async def test_a_timeout_and_a_dropped_connection_are_typed_without_the_host() -> None:
    def times_out(_request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("slow")

    def refuses(_request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("could not reach llm.test")

    with pytest.raises(LLMTimeout):
        await call(times_out)
    with pytest.raises(LLMUnavailable) as raised:
        await call(refuses)

    assert "llm.test" not in raised.value.detail


# --- Providers that do not enforce a response format -----------------------------------------


async def test_a_refused_response_format_steps_down_and_is_remembered() -> None:
    bodies: list[dict[str, Any]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        bodies.append(body)
        if "response_format" in body:
            error = {"error": {"message": "response_format json_schema is not supported"}}
            return httpx2.Response(400, json=error)
        return httpx2.Response(200, json=completion())

    provider = make_provider(handler, json_mode="schema")
    first = await provider.generate_structured(REQUEST, Answer)
    second = await provider.generate_structured(REQUEST, Answer)

    assert first.value == second.value == Answer(name="ok", count=2)
    kinds = [body.get("response_format", {}).get("type") for body in bodies]
    # schema -> object -> none for the first call; the second goes straight to none.
    assert kinds == ["json_schema", "json_object", None, None]
    assert "ANSWER FORMAT" in bodies[1]["messages"][0]["content"]


async def test_a_rejection_that_is_not_about_the_format_is_not_retried() -> None:
    calls: list[int] = []

    def handler(_request: httpx2.Request) -> httpx2.Response:
        calls.append(1)
        return httpx2.Response(400, json={"error": {"message": "context length exceeded"}})

    with pytest.raises(LLMRejected):
        await make_provider(handler).generate_structured(REQUEST, Answer)

    assert len(calls) == 1


# --- Several models --------------------------------------------------------------------------


async def test_a_model_without_allowance_rests_and_the_next_model_answers() -> None:
    asked: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        model = json.loads(request.content)["model"]
        asked.append(model)
        if model == "model-a":
            body = {"error": {"message": "Rate limit exceeded: free-models-per-day"}}
            return httpx2.Response(429, json=body, headers={"retry-after": "7200"})
        return httpx2.Response(200, json=completion(model="model-b"))

    provider = make_provider(handler, models=("model-a", "model-b"))
    first = await provider.generate_structured(REQUEST, Answer)
    second = await provider.generate_structured(REQUEST, Answer)

    assert first.model_id == second.model_id == "model-b"
    assert asked == ["model-a", "model-b", "model-b"]  # a is not asked again while it rests


async def test_a_model_that_is_set_up_wrongly_is_skipped_for_an_hour() -> None:
    asked: list[str] = []
    clock = Clock()

    def handler(request: httpx2.Request) -> httpx2.Response:
        model = json.loads(request.content)["model"]
        asked.append(model)
        if model == "typo-model":
            return httpx2.Response(404, json={"error": {"message": "no such model"}})
        return httpx2.Response(200, json=completion())

    provider = make_provider(handler, models=("typo-model", "model-b"), clock=clock)
    await provider.generate_structured(REQUEST, Answer)
    clock.now += 3000
    await provider.generate_structured(REQUEST, Answer)
    clock.now += 700  # past the hour
    await provider.generate_structured(REQUEST, Answer)

    assert asked == ["typo-model", "model-b", "model-b", "typo-model", "model-b"]


async def test_when_every_model_is_spent_the_one_that_clears_first_is_reported() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        model = json.loads(request.content)["model"]
        wait = "18000" if model == "model-a" else "600"
        body = {"error": {"message": "Rate limit exceeded: free-models-per-day"}}
        return httpx2.Response(429, json=body, headers={"retry-after": wait})

    with pytest.raises(LLMQuotaExhausted) as raised:
        await make_provider(handler, models=("model-a", "model-b")).generate_structured(
            REQUEST, Answer
        )

    assert raised.value.retry_after == 600
