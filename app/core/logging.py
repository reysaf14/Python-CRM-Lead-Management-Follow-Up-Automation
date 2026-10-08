"""Structured, sanitized application logging."""

import json
import logging
import sys
from typing import Any


class JsonFormatter(logging.Formatter):
    """Serialize only explicitly supplied safe event fields."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key in ("action", "status", "correlation_id", "error_category"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        return json.dumps(payload, ensure_ascii=True, sort_keys=True)


def configure_logging(level: str = "info") -> None:
    """Configure one sanitized stdout handler for the current process."""

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())


def log_event(
    logger: logging.Logger,
    *,
    action: str,
    status: str,
    correlation_id: str | None = None,
    error_category: str | None = None,
) -> None:
    """Write a safe event without accepting arbitrary payload fields."""

    logger.info(
        "application_event",
        extra={
            "action": action,
            "status": status,
            "correlation_id": correlation_id,
            "error_category": error_category,
        },
    )
