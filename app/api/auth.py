"""Default-deny authentication for private operator API routes."""

from __future__ import annotations

import secrets

from fastapi import Header, HTTPException

from app.core.config import get_settings


def require_operator(
    x_operator_token: str | None = Header(default=None, alias="X-Operator-Token"),
) -> None:
    """Require the configured operator token without exposing token details."""

    configured_token = get_settings().operator_access_token
    if configured_token is None:
        raise HTTPException(
            status_code=503,
            detail={"error_category": "operator_auth_not_configured"},
        )

    if x_operator_token is None or not secrets.compare_digest(
        x_operator_token,
        configured_token.get_secret_value(),
    ):
        raise HTTPException(
            status_code=401,
            detail={"error_category": "operator_auth_required"},
            headers={"WWW-Authenticate": "OperatorToken"},
        )
