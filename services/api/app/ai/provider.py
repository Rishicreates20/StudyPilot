"""The one interface through which StudyPilot talks to a language model (ADR-009).

Everything that needs a model asks an ``LLMProvider`` for *structured* output: a Pydantic model
instead of free text. Providers return only data that already validated against that model; the
caller still checks the business rules (see ``app.ai.roadmap.validation``), because a model's
answer being well-formed says nothing about it being right.

Failures are typed so the job queue can decide what to do: retry later (rate limits, outages,
timeouts), or stop now (a rejected key, blocked content, a request the provider refuses).
``user_message`` is always safe to show a learner: it never contains prompts, provider payloads
or keys.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal, Protocol

from pydantic import BaseModel


@dataclass(frozen=True)
class StructuredRequest:
    """One request for structured output."""

    system: str
    user: str
    # What this call is for ("roadmap.plan"); recorded with the usage event.
    purpose: str
    prompt_version: str
    # The structured facts ``user`` was rendered from. Real providers ignore this; the test
    # double builds its answer from it so tests never depend on parsing prompt text.
    input_data: Mapping[str, Any] = field(default_factory=lambda: {})


@dataclass(frozen=True)
class Usage:
    input_tokens: int | None
    output_tokens: int | None


@dataclass(frozen=True)
class StructuredResult[T: BaseModel]:
    value: T
    provider: str
    model_id: str
    usage: Usage
    latency_ms: int
    finish_reason: str
    # True when a test double produced the content. It is recorded on what gets stored, so the
    # UI can label it instead of passing it off as a real plan.
    synthetic: bool = False


# Every vector in the database has exactly this many numbers (ADR-008): the column type is fixed
# before the first row is written, so a provider that returns anything else is an error, not data.
EMBEDDING_DIMENSIONS = 1536


class EmbeddingTask(StrEnum):
    """What a vector is for. Retrieval models embed a question and a passage differently."""

    DOCUMENT = "document"
    QUERY = "query"


@dataclass(frozen=True)
class EmbeddingResult:
    # One vector per input text, in the same order, each of ``EMBEDDING_DIMENSIONS`` numbers and
    # scaled to length 1 (so cosine similarity and dot product agree).
    vectors: list[list[float]]
    provider: str
    model_id: str
    usage: Usage
    latency_ms: int
    synthetic: bool = False


Legibility = Literal["clear", "partly", "poor", "none"]


@dataclass(frozen=True)
class OcrResult:
    """The text a vision model read from one image (or one page), and how sure it was."""

    text: str
    # `clear` printed or neat text; `partly` some words were guesses; `poor` mostly guesses;
    # `none` nothing readable. Anything but `clear` is shown to the learner to check.
    legibility: Legibility
    provider: str
    model_id: str
    usage: Usage
    latency_ms: int
    synthetic: bool = False


class LLMProvider(Protocol):
    name: str

    async def generate_structured[T: BaseModel](
        self, request: StructuredRequest, schema: type[T]
    ) -> StructuredResult[T]:
        """Return a ``schema`` instance, or raise an ``LLMError``."""
        ...

    async def embed(self, texts: Sequence[str], task: EmbeddingTask) -> EmbeddingResult:
        """One unit-length vector of ``EMBEDDING_DIMENSIONS`` numbers per text, or ``LLMError``."""
        ...

    async def read_image_text(self, image: bytes, mime_type: str) -> OcrResult:
        """Transcribe an image (or a single-page PDF) as data; never act on what it says."""
        ...


class LLMError(Exception):
    """A failed model call. ``retryable`` says whether trying again later could succeed."""

    code = "AI_ERROR"
    retryable = False
    user_message = "The AI service could not complete the request."

    def __init__(self, detail: str = "", *, retry_after: float | None = None) -> None:
        super().__init__(detail or self.code)
        # Internal detail for logs (already stripped of prompts and keys), not for learners.
        self.detail = detail
        self.retry_after = retry_after


class LLMNotConfigured(LLMError):
    code = "AI_NOT_CONFIGURED"
    user_message = "AI generation isn't set up on this server yet."


class LLMAuthError(LLMError):
    code = "AI_AUTH_FAILED"
    user_message = "The AI provider rejected this server's credentials."


class LLMRejected(LLMError):
    code = "AI_REQUEST_REJECTED"
    user_message = "The AI provider refused the request."


class LLMBlocked(LLMError):
    code = "AI_CONTENT_BLOCKED"
    user_message = "The AI provider declined to produce a plan for this goal."


class OcrUnavailable(LLMError):
    """This server has no model that can read images (for example the built-in test provider)."""

    code = "OCR_UNAVAILABLE"
    user_message = "Reading text from images or scanned pages isn't available on this server."


class LLMQuotaExhausted(LLMError):
    """A daily allowance (a free tier's requests per day) is used up: waiting minutes won't help.

    Not retryable: the job fails at once with a message that says when it resets, instead of
    spending its attempts (and the learner's patience) on calls that cannot succeed.
    """

    code = "AI_QUOTA_EXHAUSTED"
    retryable = False
    user_message = (
        "The AI service's daily allowance for this account is used up, so nothing could be "
        "written. Try again tomorrow, or ask whoever runs this server to switch the AI model or "
        "enable billing."
    )

    def __init__(self, detail: str = "", *, retry_after: float | None = None) -> None:
        super().__init__(detail, retry_after=retry_after)
        if retry_after is not None and retry_after > 0:
            hours = max(1, round(retry_after / 3600))
            unit = "hour" if hours == 1 else "hours"
            self.user_message = (
                "The AI service's daily allowance for this account is used up, so nothing could "
                f"be written. It resets in about {hours} {unit}. You can also ask whoever runs "
                "this server to switch the AI model or enable billing."
            )


class LLMRateLimited(LLMError):
    code = "AI_RATE_LIMITED"
    retryable = True
    user_message = "The AI service is busy right now."


class LLMUnavailable(LLMError):
    code = "AI_UNAVAILABLE"
    retryable = True
    user_message = "The AI service is temporarily unavailable."


class LLMTimeout(LLMError):
    code = "AI_TIMEOUT"
    retryable = True
    user_message = "The AI service took too long to answer."


class LLMTruncated(LLMError):
    code = "AI_OUTPUT_TRUNCATED"
    retryable = True
    user_message = "The AI's answer was cut off before it finished."


class LLMInvalidOutput(LLMError):
    """The model answered, but not in the requested shape.

    ``problems`` lists what was wrong ("modules.0.topics.1.day: Input should be >= 1") without
    quoting the model's text back, so the planner can ask for a corrected answer.
    """

    code = "AI_INVALID_OUTPUT"
    user_message = "The AI returned an answer that could not be used."

    def __init__(self, detail: str = "", *, problems: list[str] | None = None) -> None:
        super().__init__(detail)
        self.problems = problems or []
