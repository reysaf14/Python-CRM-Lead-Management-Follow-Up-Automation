"""Explicit LLM adapter selection."""

from __future__ import annotations

from app.adapters.llm.client import LLMAdapterError, LLMClient, MockLLMClient
from app.core.config import Settings


def build_llm_client(settings: Settings) -> LLMClient:
    """Build only an explicitly supported adapter; never silently fall back."""

    if settings.llm_transport == "mock":
        return MockLLMClient()
    raise LLMAdapterError("live_llm_provider_not_implemented", retryable=False)
