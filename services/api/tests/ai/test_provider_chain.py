"""The main provider with others behind it: who is asked, in what order, and what is reported."""

from typing import Any

import pytest
from pydantic import BaseModel

from app.ai.chain import ProviderChain
from app.ai.provider import (
    EmbeddingResult,
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
    OcrResult,
    StructuredRequest,
    StructuredResult,
    Usage,
)

pytestmark = pytest.mark.anyio

REQUEST = StructuredRequest(system="s", user="u", purpose="lesson.write", prompt_version="test/v1")


class Answer(BaseModel):
    text: str


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class Scripted:
    """A provider that answers, or raises, as scripted; the last outcome repeats."""

    def __init__(self, name: str, *outcomes: LLMError | str) -> None:
        self.name = name
        self._outcomes = list(outcomes) or [f"from {name}"]
        self.calls = 0
        self.embedded: list[tuple[tuple[str, ...], EmbeddingTask]] = []
        self.read: list[tuple[bytes, str]] = []

    async def generate_structured[T: BaseModel](
        self, request: StructuredRequest, schema: type[T]
    ) -> StructuredResult[T]:
        outcome = self._outcomes[min(self.calls, len(self._outcomes) - 1)]
        self.calls += 1
        if isinstance(outcome, LLMError):
            raise outcome
        return StructuredResult(
            value=schema.model_validate({"text": outcome}),
            provider=self.name,
            model_id=f"{self.name}-model",
            usage=Usage(input_tokens=1, output_tokens=2),
            latency_ms=3,
            finish_reason="stop",
        )

    async def embed(self, texts: Any, task: EmbeddingTask) -> EmbeddingResult:
        self.embedded.append((tuple(texts), task))
        return EmbeddingResult(
            vectors=[[1.0]], provider=self.name, model_id="e", usage=Usage(None, None), latency_ms=1
        )

    async def read_image_text(self, image: bytes, mime_type: str) -> OcrResult:
        self.read.append((image, mime_type))
        return OcrResult(
            text="t", legibility="clear", provider=self.name, model_id="o",
            usage=Usage(None, None), latency_ms=1,
        )  # fmt: skip


def quota(hours: float) -> LLMQuotaExhausted:
    return LLMQuotaExhausted("daily", retry_after=hours * 3600)


async def ask(chain: ProviderChain) -> StructuredResult[Answer]:
    return await chain.generate_structured(REQUEST, Answer)


async def test_while_the_main_provider_can_answer_nobody_else_is_asked() -> None:
    main, backup = Scripted("gemini"), Scripted("freeco")
    chain = ProviderChain(main, [backup])

    result = await ask(chain)

    assert (result.provider, main.calls, backup.calls) == ("gemini", 1, 0)


@pytest.mark.parametrize("error", [quota(5), LLMRateLimited("busy"), LLMUnavailable("down")])
async def test_a_main_provider_that_cannot_answer_now_hands_over_to_the_next(
    error: LLMError,
) -> None:
    main, backup = Scripted("gemini", error), Scripted("freeco")
    chain = ProviderChain(main, [backup])

    result = await ask(chain)

    assert result.provider == "freeco" and result.model_id == "freeco-model"
    assert (main.calls, backup.calls) == (1, 1)


async def test_the_fallbacks_are_tried_in_order_and_a_busy_one_is_passed_over() -> None:
    main = Scripted("gemini", quota(5))
    first, second = Scripted("first", LLMRateLimited("busy")), Scripted("second")
    third = Scripted("third")
    chain = ProviderChain(main, [first, second, third])

    result = await ask(chain)

    assert result.provider == "second"
    assert (first.calls, second.calls, third.calls) == (1, 1, 0)


async def test_a_resting_fallback_is_not_asked_again_until_its_rest_is_over() -> None:
    clock = Clock()
    main = Scripted("gemini", quota(5))
    first = Scripted("first", LLMRateLimited("busy", retry_after=120), "first is back")
    second = Scripted("second")
    chain = ProviderChain(main, [first, second], clock=clock)

    await ask(chain)
    clock.now += 60
    await ask(chain)  # first still rests
    assert first.calls == 1

    clock.now += 61
    result = await ask(chain)

    assert first.calls == 2 and result.provider == "first"
    assert main.calls == 3  # the main provider is always asked first (it rests itself cheaply)


@pytest.mark.parametrize(
    "error",
    [
        LLMAuthError("bad key"),
        LLMRejected("refused"),
        LLMBlocked("blocked"),
        LLMInvalidOutput("malformed"),
        LLMTruncated("cut off"),
        LLMTimeout("slow"),
    ],
)
async def test_every_other_failure_of_the_main_provider_is_its_own_and_nobody_is_asked(
    error: LLMError,
) -> None:
    main, backup = Scripted("gemini", error), Scripted("freeco")
    chain = ProviderChain(main, [backup])

    with pytest.raises(type(error)):
        await ask(chain)

    assert backup.calls == 0


async def test_when_nobody_can_answer_the_error_that_clears_first_is_raised_with_its_wait() -> None:
    main = Scripted("gemini", quota(5))
    first = Scripted("first", LLMRateLimited("busy", retry_after=45))
    second = Scripted("second", quota(20))
    chain = ProviderChain(main, [first, second])

    with pytest.raises(LLMRateLimited) as raised:
        await ask(chain)

    assert raised.value.retry_after == 45


async def test_when_only_allowances_are_spent_the_learner_hears_when_the_first_resets() -> None:
    main = Scripted("gemini", quota(19))
    backup = Scripted("freeco", quota(4))
    chain = ProviderChain(main, [backup])

    with pytest.raises(LLMQuotaExhausted) as raised:
        await ask(chain)

    assert raised.value.retry_after == 4 * 3600
    assert "about 4 hours" in raised.value.user_message


async def test_a_fallback_that_is_set_up_wrongly_is_skipped_and_never_changes_the_error() -> None:
    main = Scripted("gemini", quota(5))
    broken = Scripted("broken", LLMAuthError("bad key"))
    chain = ProviderChain(main, [broken])

    with pytest.raises(LLMQuotaExhausted) as raised:
        await ask(chain)

    # Exactly what the learner would have been told with no fallback at all.
    assert raised.value.retry_after == 5 * 3600
    # And it is not asked again for a while.
    with pytest.raises(LLMQuotaExhausted):
        await ask(chain)
    assert broken.calls == 1


async def test_a_wrongly_set_up_fallback_does_not_stop_the_next_one_answering() -> None:
    main = Scripted("gemini", quota(5))
    broken, working = Scripted("broken", LLMRejected("no such model")), Scripted("working")
    chain = ProviderChain(main, [broken, working])

    assert (await ask(chain)).provider == "working"


async def test_a_fallback_that_answers_badly_is_not_rested_and_the_next_gets_a_try() -> None:
    main = Scripted("gemini", quota(5))
    sloppy = Scripted("sloppy", LLMInvalidOutput("malformed"), "second time lucky")
    working = Scripted("working")
    chain = ProviderChain(main, [sloppy, working])

    assert (await ask(chain)).provider == "working"
    assert (await ask(chain)).provider == "sloppy"  # not resting: asked first again


async def test_if_every_fallback_answers_badly_the_caller_gets_that_to_repair() -> None:
    main = Scripted("gemini", quota(5))
    first = Scripted("first", LLMInvalidOutput("malformed", problems=["count: too small"]))
    second = Scripted("second", LLMTruncated("cut off"))
    chain = ProviderChain(main, [first, second])

    with pytest.raises(LLMTruncated):
        await ask(chain)


async def test_a_main_provider_that_has_recovered_is_used_again_straight_away() -> None:
    main = Scripted("gemini", quota(5), "gemini is back")
    backup = Scripted("freeco")
    chain = ProviderChain(main, [backup])

    assert (await ask(chain)).provider == "freeco"
    assert (await ask(chain)).provider == "gemini"


async def test_embeddings_and_reading_pictures_always_use_the_main_provider() -> None:
    main, backup = Scripted("gemini", quota(5)), Scripted("freeco")
    chain = ProviderChain(main, [backup])

    embedded = await chain.embed(["a", "b"], EmbeddingTask.QUERY)
    read = await chain.read_image_text(b"png", "image/png")

    assert embedded.provider == read.provider == "gemini"
    assert main.embedded == [(("a", "b"), EmbeddingTask.QUERY)]
    assert main.read == [(b"png", "image/png")]
    assert backup.embedded == [] and backup.read == []


async def test_the_chain_is_called_what_the_main_provider_is_called() -> None:
    assert ProviderChain(Scripted("gemini"), [Scripted("freeco")]).name == "gemini"
