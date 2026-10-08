import json
import logging

from app.core.logging import JsonFormatter, log_event


def test_structured_logging_contains_only_safe_event_fields() -> None:
    logger = logging.getLogger("test.safe.logging")
    record = logger.makeRecord(
        logger.name,
        logging.INFO,
        __file__,
        1,
        "application_event",
        (),
        None,
        extra={"action": "bootstrap", "status": "ready", "correlation_id": "synthetic-001"},
    )

    payload = json.loads(JsonFormatter().format(record))

    assert payload == {
        "action": "bootstrap",
        "correlation_id": "synthetic-001",
        "level": "info",
        "logger": "test.safe.logging",
        "message": "application_event",
        "status": "ready",
    }


def test_log_event_does_not_accept_a_raw_payload_argument() -> None:
    logger = logging.getLogger("test.safe.signature")

    log_event(logger, action="bootstrap", status="ready")
