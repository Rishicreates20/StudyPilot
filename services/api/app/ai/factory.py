"""Choose the language-model provider from configuration."""

import httpx2

from app.ai.fake import FakeProvider
from app.ai.fake_roadmap import roadmap_responder
from app.ai.gemini import GeminiProvider
from app.ai.provider import LLMNotConfigured, LLMProvider
from app.core.config import LlmProviderName, Settings


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
        return FakeProvider(roadmap_responder)
    raise LLMNotConfigured("LLM_PROVIDER is not set")
