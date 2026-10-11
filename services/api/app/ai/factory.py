"""Choose the language-model provider from configuration."""

import httpx2

from app.ai.fake import FakeProvider, Reply
from app.ai.fake_lesson import lesson_responder
from app.ai.fake_quiz import grading_responder, quiz_responder
from app.ai.fake_roadmap import roadmap_responder
from app.ai.gemini import GeminiProvider
from app.ai.provider import LLMNotConfigured, LLMProvider, StructuredRequest
from app.core.config import LlmProviderName, Settings


def builtin_responder(request: StructuredRequest) -> Reply:
    """The test double's answer, chosen by what the call is for (``lesson.*``, ``quiz.*``...)."""
    if request.purpose.startswith("lesson."):
        return lesson_responder(request)
    if request.purpose.startswith("quiz."):
        return quiz_responder(request)
    if request.purpose.startswith("grade."):
        return grading_responder(request)
    return roadmap_responder(request)


def build_provider(settings: Settings, client: httpx2.AsyncClient) -> LLMProvider:
    """The provider the worker should use, or ``LLMNotConfigured`` if there isn't one."""
    if settings.llm_provider is LlmProviderName.GEMINI:
        if settings.gemini_api_key is None:
            raise LLMNotConfigured("GEMINI_API_KEY is not set")
        return GeminiProvider(
            client,
            api_key=settings.gemini_api_key,
            model=settings.gemini_model,
            base_url=settings.gemini_base_url,
            max_output_tokens=settings.llm_max_output_tokens,
            temperature=settings.llm_temperature,
            timeout_seconds=settings.llm_timeout_seconds,
        )
    if settings.llm_provider is LlmProviderName.FAKE:
        return FakeProvider(builtin_responder)
    raise LLMNotConfigured("LLM_PROVIDER is not set")
