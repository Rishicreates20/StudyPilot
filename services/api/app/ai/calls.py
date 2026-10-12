"""One model call, recorded: shared by every stage that asks a provider for structured output.

``call_structured`` wraps ``LLMProvider.generate_structured`` and tells an observer about the call
whether it succeeded or failed, so the usage ledger (``ai_usage_events``) sees every attempt. The
observer never receives prompts or model output, only counts, timings and codes.
"""

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

from pydantic import BaseModel

from app.ai.provider import (
    EmbeddingResult,
    EmbeddingTask,
    LLMError,
    LLMProvider,
    OcrResult,
    StructuredRequest,
    StructuredResult,
    Usage,
)


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


async def _record(
    observer: Observer | None,
    *,
    purpose: str,
    prompt_version: str,
    provider: str,
    model_id: str,
    usage: Usage | None,
    latency_ms: int,
    finish_reason: str,
    error_code: str | None = None,
) -> None:
    if observer is None:
        return
    await observer(
        CallRecord(
            purpose=purpose,
            provider=provider,
            model_id=model_id,
            prompt_version=prompt_version,
            input_tokens=usage.input_tokens if usage else None,
            output_tokens=usage.output_tokens if usage else None,
            latency_ms=latency_ms,
            finish_reason=finish_reason,
            error_code=error_code,
        )
    )


async def call_embed(
    provider: LLMProvider,
    texts: Sequence[str],
    task: EmbeddingTask,
    *,
    purpose: str,
    observer: Observer | None,
) -> EmbeddingResult:
    """Embed ``texts`` and tell the observer, as ``call_structured`` does for generation."""
    try:
        result = await provider.embed(texts, task)
    except LLMError as exc:
        await _record(
            observer, purpose=purpose, prompt_version="embed/v1", provider=provider.name,
            model_id="", usage=None, latency_ms=0, finish_reason="", error_code=exc.code,
        )  # fmt: skip
        raise
    await _record(
        observer, purpose=purpose, prompt_version="embed/v1", provider=result.provider,
        model_id=result.model_id, usage=result.usage, latency_ms=result.latency_ms,
        finish_reason="STOP",
    )  # fmt: skip
    return result


async def call_ocr(
    provider: LLMProvider,
    image: bytes,
    mime_type: str,
    *,
    prompt_version: str,
    observer: Observer | None,
) -> OcrResult:
    """Read one image or page with the vision model and tell the observer."""
    try:
        result = await provider.read_image_text(image, mime_type)
    except LLMError as exc:
        await _record(
            observer, purpose="ocr.page", prompt_version=prompt_version, provider=provider.name,
            model_id="", usage=None, latency_ms=0, finish_reason="", error_code=exc.code,
        )  # fmt: skip
        raise
    await _record(
        observer, purpose="ocr.page", prompt_version=prompt_version, provider=result.provider,
        model_id=result.model_id, usage=result.usage, latency_ms=result.latency_ms,
        finish_reason="STOP",
    )  # fmt: skip
    return result
