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

from app.ai.provider import (
    LLMInvalidOutput,
    StructuredRequest,
    StructuredResult,
    Usage,
)

Reply = BaseModel | dict[str, Any] | BaseException
Responder = Callable[[StructuredRequest], Reply]

FAKE_MODEL_ID = "fake-planner-1"


class FakeProvider:
    name = "fake"

    def __init__(self, responder: Responder | None = None, *, script: Sequence[Reply] = ()) -> None:
        self._responder = responder
        self._script: deque[Reply] = deque(script)
        self.requests: list[StructuredRequest] = []

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
