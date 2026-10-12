"""A deterministic stand-in for a language model: for tests and explicit local development ONLY.

``LLM_PROVIDER=fake`` is refused in staging and production (see ``Settings``). Everything it
returns is marked ``synthetic``; the roadmap it stores carries that flag and the UI labels it as a
sample, so a stand-in plan can never be mistaken for AI-generated content.

Two ways to drive it:

* ``FakeProvider(responder)``: ``responder(request)`` returns the reply for each call, for the
  built-in roadmap behaviour used by local runs and the browser tests;
* ``FakeProvider(script=[...])``: a list of replies consumed in order, for tests that need an
  exact sequence (a bad answer, then a good one; a rate limit, then success).

A reply may be a model instance, a dict (validated like real output), or an exception to raise.
"""

from collections import deque
from collections.abc import Callable, Sequence
from typing import Any

from pydantic import BaseModel, ValidationError

from app.ai.fake_embedding import hashed_vector
from app.ai.provider import (
    EmbeddingResult,
    EmbeddingTask,
    LLMInvalidOutput,
    OcrResult,
    OcrUnavailable,
    StructuredRequest,
    StructuredResult,
    Usage,
)

Reply = BaseModel | dict[str, Any] | BaseException
Responder = Callable[[StructuredRequest], Reply]

FAKE_MODEL_ID = "fake-planner-1"
FAKE_EMBEDDING_MODEL_ID = "fake-embedding-1"

# What a test's ``ocr`` callback answers for one image: a reading, or an error to raise.
OcrReply = OcrResult | BaseException
OcrResponder = Callable[[bytes, str], OcrReply]


_SAMPLE_READING = (
    "[Sample text from the built-in test provider, which cannot read pictures. A real model "
    "would give the words in your image here.] Ownership means each value has one owner."
)


def sample_ocr(image: bytes, mime_type: str) -> OcrResult:
    """What the built-in provider "reads" from any picture: clearly marked sample text.

    It reports ``partly`` legibility on purpose, so local runs and browser tests go through the
    review step a real handwriting reading would.
    """
    return OcrResult(
        text=_SAMPLE_READING,
        legibility="partly",
        provider="fake",
        model_id="fake-ocr-1",
        usage=Usage(input_tokens=0, output_tokens=0),
        latency_ms=0,
        synthetic=True,
    )


class FakeProvider:
    name = "fake"

    def __init__(
        self,
        responder: Responder | None = None,
        *,
        script: Sequence[Reply] = (),
        ocr: OcrResponder | None = None,
    ) -> None:
        self._responder = responder
        self._script: deque[Reply] = deque(script)
        self._ocr = ocr
        self.requests: list[StructuredRequest] = []
        # Every batch of texts embedded, and every image read, for tests to inspect.
        self.embedded: list[tuple[EmbeddingTask, list[str]]] = []
        self.images_read: list[tuple[int, str]] = []

    async def generate_structured[T: BaseModel](
        self, request: StructuredRequest, schema: type[T]
    ) -> StructuredResult[T]:
        self.requests.append(request)
        if self._script:
            reply = self._script.popleft()
        elif self._responder is not None:
            reply = self._responder(request)
        else:
            raise AssertionError("FakeProvider has no reply left for this request")
        if isinstance(reply, BaseException):
            raise reply
        try:
            value = reply if isinstance(reply, schema) else schema.model_validate(reply)
        except ValidationError as exc:
            problems = [
                f"{'.'.join(str(p) for p in e['loc']) or 'answer'}: {e['msg']}"
                for e in exc.errors(include_input=False, include_url=False)
            ]
            raise LLMInvalidOutput(
                "fake reply did not match the schema", problems=problems
            ) from None
        return StructuredResult(
            value=value,
            provider=self.name,
            model_id=FAKE_MODEL_ID,
            usage=Usage(input_tokens=0, output_tokens=0),
            latency_ms=0,
            finish_reason="STOP",
            synthetic=True,
        )

    async def embed(self, texts: Sequence[str], task: EmbeddingTask) -> EmbeddingResult:
        """Hashed bag-of-words vectors: similar wording, similar vectors (see fake_embedding)."""
        self.embedded.append((task, list(texts)))
        return EmbeddingResult(
            vectors=[hashed_vector(text) for text in texts],
            provider=self.name,
            model_id=FAKE_EMBEDDING_MODEL_ID,
            usage=Usage(input_tokens=0, output_tokens=None),
            latency_ms=0,
            synthetic=True,
        )

    async def read_image_text(self, image: bytes, mime_type: str) -> OcrResult:
        """Reads nothing by itself: a test says what an image contains, or there is no OCR."""
        self.images_read.append((len(image), mime_type))
        if self._ocr is None:
            raise OcrUnavailable("the built-in test provider cannot read images")
        reply = self._ocr(image, mime_type)
        if isinstance(reply, BaseException):
            raise reply
        return reply
