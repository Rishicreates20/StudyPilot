"""The main provider, with other providers behind it for when it cannot answer.

A free tier gives each provider (and each model) a small allowance, so running out is normal. The
chain asks the main provider first. Only when that one is out of allowance, rate limited or
unavailable does it ask the others in order, each at most once per call, skipping any that is
resting (see ``app.ai.bench``). The learner sees a failure only when every one of them is
unavailable at the same moment, and then the message is the most useful one: the allowance that
resets soonest, with how long that takes.

Only *generation* falls back. Embeddings and reading pictures always go to the main provider: every
vector in the database must come from one recorded model (ADR-045), and the others are not asked to
see images. Anything else that goes wrong with the main provider (a rejected key, blocked content,
an answer that was malformed or cut off) is its own error, as without a chain, so a fault in the
main configuration stays loud instead of being papered over.

A fallback that is set up wrongly (a rejected key, an unknown model) rests for an hour and is
reported in the server log, never to the learner: it must not make things worse than having none.
A fallback that answers badly (malformed, cut off, blocked) is not resting; the next one is tried,
and if none does better that answer's error goes to the caller, who may ask for a repair.
"""

import time
from collections.abc import Callable, Sequence
from typing import Protocol

import structlog
from pydantic import BaseModel

from app.ai.bench import BUSY, MISCONFIGURED, Bench, rest_for, soonest
from app.ai.provider import (
    EmbeddingResult,
    EmbeddingTask,
    LLMBlocked,
    LLMError,
    LLMInvalidOutput,
    LLMProvider,
    LLMQuotaExhausted,
    LLMRateLimited,
    LLMTruncated,
    LLMUnavailable,
    OcrResult,
    StructuredRequest,
    StructuredResult,
)

log = structlog.get_logger("app.ai.chain")

# What the main provider answers when it simply cannot take the request now.
_PRIMARY_BUSY = (LLMQuotaExhausted, LLMRateLimited, LLMUnavailable)
# A fallback that did answer, but badly: the next one may do better, and the caller may repair.
_BAD_ANSWER = (LLMInvalidOutput, LLMTruncated, LLMBlocked)


class StructuredGenerator(Protocol):
    """What a fallback must offer: structured generation, and a name to record."""

    name: str

    async def generate_structured[T: BaseModel](
        self, request: StructuredRequest, schema: type[T]
    ) -> StructuredResult[T]: ...


class ProviderChain:
    def __init__(
        self,
        primary: LLMProvider,
        fallbacks: Sequence[StructuredGenerator],
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._primary = primary
        self._fallbacks = {fallback.name: fallback for fallback in fallbacks}
        self._bench = Bench("providers", clock=clock)
        # What the main provider is called: similarity bars and the worker's log key off it.
        self.name = primary.name

    async def generate_structured[T: BaseModel](
        self, request: StructuredRequest, schema: type[T]
    ) -> StructuredResult[T]:
        try:
            return await self._primary.generate_structured(request, schema)
        except _PRIMARY_BUSY as exc:
            primary_error: LLMError = exc

        busy: list[tuple[float, LLMError]] = [(rest_for(primary_error), primary_error)]
        bad_answer: LLMError | None = None
        for name, fallback in self._fallbacks.items():
            resting = self._bench.resting(name)
            if resting is not None:
                left, error = resting
                if not isinstance(error, MISCONFIGURED):
                    busy.append((left, error))
                continue
            try:
                result = await fallback.generate_structured(request, schema)
            except BUSY as exc:
                busy.append((self._bench.rest(name, exc), exc))
                continue
            except MISCONFIGURED as exc:
                self._bench.rest(name, exc)
                log.warning("ai.fallback_misconfigured", provider=name, code=exc.code)
                continue
            except _BAD_ANSWER as exc:
                bad_answer = exc
                continue
            log.info(
                "ai.fallback_used",
                primary=self._primary.name,
                primary_code=primary_error.code,
                provider=name,
                model=result.model_id,
            )
            return result

        if bad_answer is not None:
            raise bad_answer
        raise soonest(busy)

    async def embed(self, texts: Sequence[str], task: EmbeddingTask) -> EmbeddingResult:
        return await self._primary.embed(texts, task)

    async def read_image_text(self, image: bytes, mime_type: str) -> OcrResult:
        return await self._primary.read_image_text(image, mime_type)
