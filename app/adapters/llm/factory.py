"""Explicit LLM adapter selection."""

from __future__ import annotations

from app.adapters.llm.client import DeepSeekLLMClient, LLMAdapterError, LLMClient, MockLLMClient
from app.core.config import DEEPSEEK_DEFAULT_BASE_URL, Settings


def build_llm_client(settings: Settings) -> LLMClient:
    """Build only an explicitly supported adapter; never silently fall back."""

    if settings.llm_transport == "mock":
        return MockLLMClient()
    if settings.llm_provider != "deepseek":
        raise LLMAdapterError("unsupported_live_llm_provider", retryable=False)
    assert settings.llm_api_key is not None
    return DeepSeekLLMClient(
        api_key=settings.llm_api_key.get_secret_value(),
        base_url=settings.llm_base_url or DEEPSEEK_DEFAULT_BASE_URL,
    )
