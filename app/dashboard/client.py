"""Small provider-neutral HTTP client for the private CRM API."""

from __future__ import annotations

from typing import Any

import httpx


class CRMAPIError(RuntimeError):
    """Raised when the internal API cannot provide a dashboard response."""


class CRMAPIClient:
    """Call only the internal operator API; never call Gmail or an LLM directly."""

    def __init__(
        self,
        base_url: str,
        *,
        access_token: str | None = None,
        timeout_seconds: float = 5.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._access_token = access_token
        self._timeout_seconds = timeout_seconds

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> Any:
        try:
            headers = (
                {"X-Operator-Token": self._access_token}
                if self._access_token
                else None
            )
            response = httpx.request(
                method,
                f"{self._base_url}{path}",
                params=params,
                json=json,
                headers=headers,
                timeout=self._timeout_seconds,
            )
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise CRMAPIError("crm_api_unavailable") from error

    def summary(self) -> dict[str, Any]:
        return self._request("GET", "/api/v1/dashboard/summary")

    def leads(
        self,
        *,
        status: str | None = None,
        priority: str | None = None,
        search: str | None = None,
        review_only: bool = False,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        return self._request(
            "GET",
            "/api/v1/leads",
            params={
                "status": status,
                "priority": priority,
                "search": search,
                "review_only": review_only,
                "limit": limit,
            },
        )

    def lead(self, lead_id: int) -> dict[str, Any]:
        return self._request("GET", f"/api/v1/leads/{lead_id}")

    def follow_ups(self, *, due_only: bool = True, limit: int = 100) -> list[dict[str, Any]]:
        return self._request(
            "GET",
            "/api/v1/follow-ups",
            params={"due_only": due_only, "limit": limit},
        )

    def manual_review(self, *, limit: int = 100) -> list[dict[str, Any]]:
        return self._request("GET", "/api/v1/manual-review", params={"limit": limit})

    def record_response(self, *, lead_id: int, correlation_id: str) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/api/v1/leads/{lead_id}/response",
            json={"correlation_id": correlation_id},
        )
