"""One model call, recorded: shared by every stage that asks a provider for structured output.

``call_structured`` wraps ``LLMProvider.generate_structured`` and tells an observer about the call
whether it succeeded or failed, so the usage ledger (``ai_usage_events``) sees every attempt. The
observer never receives prompts or model output, only counts, timings and codes.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from pydantic import BaseModel

from app.ai.provider import LLMError, LLMProvider, StructuredRequest, StructuredResult


@dataclass(frozen=True)
class CallRecord:
    """One model call, for the usage ledger. Success and failure are both recorded."""

    purpose: str
    provider: str
    model_id: str
    prompt_version: str
    input_tokens: int | None
    output_tokens: int | None
    latency_ms: int
    finish_reason: str
    error_code: str | None = None


Observer = Callable[[CallRecord], Awaitable[None]]


async def call_structured[T: BaseModel](
    provider: LLMProvider,
    request: StructuredRequest,
    schema: type[T],
    observer: Observer | None,
) -> StructuredResult[T]:
    try:
        result = await provider.generate_structured(request, schema)
    except LLMError as exc:
        if observer is not None:
            await observer(
                CallRecord(
                    purpose=request.purpose,
                    provider=provider.name,
                    model_id="",
                    prompt_version=request.prompt_version,
                    input_tokens=None,
                    output_tokens=None,
                    latency_ms=0,
                    finish_reason="",
                    error_code=exc.code,
                )
            )
        raise
    if observer is not None:
        await observer(
            CallRecord(
                purpose=request.purpose,
                provider=result.provider,
                model_id=result.model_id,
                prompt_version=request.prompt_version,
                input_tokens=result.usage.input_tokens,
                output_tokens=result.usage.output_tokens,
                latency_ms=result.latency_ms,
                finish_reason=result.finish_reason,
            )
        )
    return result
