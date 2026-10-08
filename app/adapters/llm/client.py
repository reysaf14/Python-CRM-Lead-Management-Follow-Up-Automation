"""Provider-neutral LLM boundary for one structured extraction call."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol


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
