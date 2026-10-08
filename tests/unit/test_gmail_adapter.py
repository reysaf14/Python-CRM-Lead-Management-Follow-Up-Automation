import base64
from datetime import datetime, timezone

import pytest

from app.adapters.gmail.client import (
    GmailAdapterError,
    GmailPage,
    MockGmailAdapter,
    LiveGmailAdapter,
    MAX_MIME_BODY_BYTES,
    MAX_MIME_DEPTH,
    MAX_PROVIDER_MESSAGE_BYTES,
    extract_text_body,
    normalize_gmail_message,
)
from app.core.config import Settings


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


def test_mime_body_limit_rejects_oversized_text_before_concatenation() -> None:
    oversized = _encode("x" * (MAX_MIME_BODY_BYTES + 1))

    with pytest.raises(GmailAdapterError, match="mime_body_too_large"):
        extract_text_body(
            {
                "mimeType": "text/plain",
                "body": {"data": oversized},
            }
        )


def test_mime_depth_limit_rejects_deeply_nested_parts() -> None:
    payload: dict[str, object] = {
        "mimeType": "multipart/mixed",
        "parts": [],
    }
    current = payload
    for _ in range(MAX_MIME_DEPTH + 1):
        child: dict[str, object] = {"mimeType": "multipart/mixed", "parts": []}
        current["parts"] = [child]
        current = child

    with pytest.raises(GmailAdapterError, match="mime_depth_exceeded"):
        extract_text_body(payload)


class _Request:
    def __init__(self, value: dict[str, object]) -> None:
        self._value = value

    def execute(self) -> dict[str, object]:
        return self._value


class _FakeLabels:
    def list(self, *, userId: str) -> _Request:
        return _Request({"labels": [{"name": "Sales Leads", "id": "label-sales"}]})


class _FakeMessages:
    def __init__(
        self,
        *,
        message_ids: tuple[str, ...] = (),
        size_estimate: int | None = 0,
    ) -> None:
        self.message_ids = message_ids
        self.size_estimate = size_estimate
        self.get_formats: list[str] = []

    def list(self, **_: object) -> _Request:
        return _Request({"messages": [{"id": message_id} for message_id in self.message_ids]})

    def get(self, *, format: str, **_: object) -> _Request:
        self.get_formats.append(format)
        if format == "metadata":
            metadata: dict[str, object] = {}
            if self.size_estimate is not None:
                metadata["sizeEstimate"] = self.size_estimate
            return _Request(metadata)
        return _Request(
            {
                "id": "message-live-001",
                "threadId": "thread-live-001",
                "internalDate": "1735689600000",
                "payload": {
                    "headers": [
                        {"name": "From", "value": "sender@example.invalid"},
                        {"name": "Subject", "value": "Synthetic live message"},
                    ],
                    "mimeType": "text/plain",
                    "body": {"data": _encode("Synthetic body")},
                },
            }
        )


class _FakeUsers:
    def __init__(
        self,
        email_address: str,
        *,
        message_ids: tuple[str, ...] = (),
        size_estimate: int | None = 0,
    ) -> None:
        self.email_address = email_address
        self._messages = _FakeMessages(
            message_ids=message_ids,
            size_estimate=size_estimate,
        )

    def getProfile(self, *, userId: str) -> _Request:
        return _Request({"emailAddress": self.email_address})

    def labels(self) -> _FakeLabels:
        return _FakeLabels()

    def messages(self) -> _FakeMessages:
        return self._messages


class _FakeGmailService:
    def __init__(
        self,
        email_address: str,
        *,
        message_ids: tuple[str, ...] = (),
        size_estimate: int | None = 0,
    ) -> None:
        self._users = _FakeUsers(
            email_address,
            message_ids=message_ids,
            size_estimate=size_estimate,
        )

    def users(self) -> _FakeUsers:
        return self._users


def _live_settings(mailbox_address: str) -> Settings:
    return Settings(
        APP_ENV="local",
        DATABASE_URL="postgresql+psycopg://crm:test@localhost:5432/crm",
        OPERATOR_ACCESS_TOKEN="synthetic-operator-token",
        GMAIL_TRANSPORT="live",
        GMAIL_OAUTH_CLIENT_ID="synthetic-client-id",
        GMAIL_OAUTH_CLIENT_SECRET="synthetic-client-secret",
        GMAIL_OAUTH_REFRESH_TOKEN="synthetic-refresh-token",
        GMAIL_MAILBOX_ADDRESS=mailbox_address,
        GMAIL_LABEL_NAME="Sales Leads",
        LLM_TRANSPORT="mock",
        OPERATOR_ACCESS_MODE="private-host-only",
    )


def test_live_gmail_rejects_authenticated_mailbox_identity_mismatch() -> None:
    adapter = LiveGmailAdapter(
        _live_settings("sales@example.invalid"),
        service=_FakeGmailService("other@example.invalid"),
    )

    with pytest.raises(GmailAdapterError, match="mailbox_identity_mismatch"):
        adapter.list_messages(label_name="Sales Leads", cursor=None)


def test_live_gmail_verifies_matching_identity_before_fetching_label() -> None:
    adapter = LiveGmailAdapter(
        _live_settings("sales@example.invalid"),
        service=_FakeGmailService("SALES@example.invalid"),
    )

    page = adapter.list_messages(label_name="Sales Leads", cursor=None)

    assert page.messages == ()


def test_live_gmail_rejects_provider_size_before_full_message_fetch() -> None:
    service = _FakeGmailService(
        "sales@example.invalid",
        message_ids=("message-too-large",),
        size_estimate=MAX_PROVIDER_MESSAGE_BYTES + 1,
    )
    adapter = LiveGmailAdapter(_live_settings("sales@example.invalid"), service=service)

    with pytest.raises(GmailAdapterError, match="provider_message_size_exceeded"):
        adapter.list_messages(label_name="Sales Leads", cursor=None)

    assert service.users().messages().get_formats == ["metadata"]


def test_live_gmail_rejects_missing_provider_size_before_full_message_fetch() -> None:
    service = _FakeGmailService(
        "sales@example.invalid",
        message_ids=("message-missing-size",),
        size_estimate=None,
    )
    adapter = LiveGmailAdapter(_live_settings("sales@example.invalid"), service=service)

    with pytest.raises(GmailAdapterError, match="missing_provider_size_estimate"):
        adapter.list_messages(label_name="Sales Leads", cursor=None)

    assert service.users().messages().get_formats == ["metadata"]
