"""Synthetic tests for the bounded DeepSeek-compatible LLM adapter."""

from __future__ import annotations

import json

import httpx
import pytest

from app.adapters.llm.client import DeepSeekLLMClient, LLMAdapterError, LLMExtractionRequest


def _request() -> LLMExtractionRequest:
    return LLMExtractionRequest(
        prompt='Return JSON for this synthetic email.',
        model="synthetic-model",
        timeout_seconds=3,
    )


def _client(
    handler,
) -> DeepSeekLLMClient:
    return DeepSeekLLMClient(
        api_key="synthetic-api-key",
        base_url="https://api.deepseek.com",
        transport=httpx.MockTransport(handler),
    )


def test_deepseek_client_sends_bounded_json_request() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert request.url == "https://api.deepseek.com/chat/completions"
        assert request.headers["authorization"] == "Bearer synthetic-api-key"
        assert body["response_format"] == {"type": "json_object"}
        assert body["stream"] is False
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"intent":"sales_inquiry"}'}}]},
        )

    result = _client(handler).extract_structured(_request())

    assert result == {"intent": "sales_inquiry"}


@pytest.mark.parametrize(
    ("status_code", "category", "retryable"),
    [
        (401, "llm_auth_failed", False),
        (429, "llm_rate_limited", True),
        (503, "llm_provider_failed", True),
        (422, "llm_request_rejected", False),
    ],
)
def test_deepseek_client_maps_provider_failures_without_payload_leak(
    status_code: int,
    category: str,
    retryable: bool,
) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, text="synthetic provider detail")

    with pytest.raises(LLMAdapterError, match=category) as error:
        _client(handler).extract_structured(_request())

    assert error.value.retryable is retryable
    assert "synthetic provider detail" not in str(error.value)


def test_deepseek_client_routes_invalid_json_to_safe_failure() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "not-json"}}]},
        )

    with pytest.raises(LLMAdapterError, match="llm_invalid_response"):
        _client(handler).extract_structured(_request())


def test_deepseek_client_maps_timeout_to_retryable_failure() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("synthetic timeout")

    with pytest.raises(LLMAdapterError, match="llm_timeout") as error:
        _client(handler).extract_structured(_request())

    assert error.value.retryable is True
