"""Dashboard access helpers for the private operator surface."""

from __future__ import annotations

import secrets


def is_valid_operator_token(candidate: str, expected: str | None) -> bool:
    """Compare dashboard credentials without exposing the configured token."""

    if not expected or not candidate:
        return False
    return secrets.compare_digest(candidate, expected)
