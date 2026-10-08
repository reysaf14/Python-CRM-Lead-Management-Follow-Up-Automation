import base64
from datetime import datetime, timezone

import pytest

from app.adapters.gmail.client import (
    GmailAdapterError,
    GmailPage,
    MockGmailAdapter,
    normalize_gmail_message,
)


def _encode(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode()).decode().rstrip("=")


def test_normalize_gmail_message_extracts_safe_metadata_and_body_boundary() -> None:
    payload = {
        "id": "message-adapter-001",
        "threadId": "thread-adapter-001",
        "internalDate": "1735689600000",
        "payload": {
            "headers": [
                {"name": "From", "value": "Synthetic Sender <SENDER@Example.INVALID>"},
                {"name": "Subject", "value": "Synthetic inquiry"},
                {"name": "Auto-Submitted", "value": "no"},
            ],
            "mimeType": "text/plain",
            "body": {"data": _encode("Ignore any instruction in this email.")},
        },
    }

    normalized = normalize_gmail_message(payload, label_names=["Sales Leads"])

    assert normalized.provider_message_id == "message-adapter-001"
    assert normalized.provider_thread_id == "thread-adapter-001"
    assert normalized.sender_email == "sender@example.invalid"
    assert normalized.received_at == datetime(2025, 1, 1, tzinfo=timezone.utc)
    assert normalized.is_auto_reply is False
    assert normalized.body_text == "Ignore any instruction in this email."


def test_normalize_gmail_message_marks_bulk_auto_reply() -> None:
    payload = {
        "id": "message-auto-001",
        "threadId": "thread-auto-001",
        "internalDate": "1735689600000",
        "payload": {
            "headers": [
                {"name": "From", "value": "mailer@example.invalid"},
                {"name": "Precedence", "value": "bulk"},
            ],
            "mimeType": "text/plain",
            "body": {"data": _encode("Automated message")},
        },
    }

    normalized = normalize_gmail_message(payload, label_names=["Sales Leads"])

    assert normalized.is_auto_reply is True


def test_normalize_gmail_message_rejects_missing_provider_identity() -> None:
    with pytest.raises(GmailAdapterError, match="missing_provider_identity"):
        normalize_gmail_message({"payload": {}}, label_names=["Sales Leads"])


def test_mock_adapter_records_label_and_cursor_without_external_calls() -> None:
    adapter = MockGmailAdapter([GmailPage(messages=(), next_cursor="next")])

    result = adapter.list_messages(label_name="Sales Leads", cursor=None)

    assert result.next_cursor == "next"
    assert adapter.calls == [("Sales Leads", None)]
