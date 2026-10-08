"""Provider-neutral LLM boundary for one structured extraction call."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx


class LLMAdapterError(RuntimeError):
    """Safe LLM failure with a stable category and retry policy."""

    def __init__(self, category: str, *, retryable: bool = True) -> None:
        self.category = category
        self.retryable = retryable
        super().__init__(category)


@dataclass(frozen=True)
class LLMExtractionRequest:
    """One bounded request containing only the approved extraction prompt."""

    prompt: str = field(repr=False)
    model: str | None
    timeout_seconds: int


class LLMClient(Protocol):
    """Minimal provider-neutral interface used by extraction business logic."""

    def extract_structured(self, request: LLMExtractionRequest) -> Mapping[str, Any]:
        """Return one structured object or raise a categorized adapter error."""


class MockLLMClient:
    """Deterministic mock client for tests and isolated local execution."""

    def __init__(
        self,
        responses: Sequence[Mapping[str, Any]] = (),
        error: LLMAdapterError | None = None,
    ) -> None:
        self._responses = tuple(dict(response) for response in responses)
        self._error = error
        self.calls = 0
        self.requests: list[LLMExtractionRequest] = []

    def extract_structured(self, request: LLMExtractionRequest) -> Mapping[str, Any]:
        self.calls += 1
        self.requests.append(request)
        if self._error is not None:
            raise self._error
        if self.calls <= len(self._responses):
            return dict(self._responses[self.calls - 1])
        # A configured mock without a response must never invent a qualified lead.
        return {
            "intent": "unknown",
            "service_interest": None,
            "stated_budget": None,
            "business_summary": None,
            "confidence": 0.0,
            "ambiguity_flags": ["mock_response_not_configured"],
        }


class DeepSeekLLMClient:
    """Bounded DeepSeek JSON client behind the provider-neutral LLM contract."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._endpoint = base_url.rstrip("/") + "/chat/completions"
        self._transport = transport

    def extract_structured(self, request: LLMExtractionRequest) -> Mapping[str, Any]:
        if not request.model:
            raise LLMAdapterError("llm_model_missing", retryable=False)

        payload = {
            "model": request.model,
            "messages": [{"role": "user", "content": request.prompt}],
            "response_format": {"type": "json_object"},
            "temperature": 0,
            "stream": False,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        try:
            with httpx.Client(
                timeout=request.timeout_seconds,
                transport=self._transport,
            ) as client:
                response = client.post(self._endpoint, headers=headers, json=payload)
        except httpx.TimeoutException:
            raise LLMAdapterError("llm_timeout", retryable=True) from None
        except httpx.RequestError:
            raise LLMAdapterError("llm_transport_failed", retryable=True) from None

        if response.status_code in {401, 403}:
            raise LLMAdapterError("llm_auth_failed", retryable=False)
        if response.status_code == 429:
            raise LLMAdapterError("llm_rate_limited", retryable=True) from None
        if response.status_code >= 500:
            raise LLMAdapterError("llm_provider_failed", retryable=True) from None
        if response.status_code >= 400:
            raise LLMAdapterError("llm_request_rejected", retryable=False) from None

        try:
            document = response.json()
            content = document["choices"][0]["message"]["content"]
            result = json.loads(content)
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError):
            raise LLMAdapterError("llm_invalid_response", retryable=False) from None
        if not isinstance(result, Mapping):
            raise LLMAdapterError("llm_invalid_response", retryable=False)
        return result
