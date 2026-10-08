"""Provider-neutral Gmail message contract and Gmail API adapter."""

from __future__ import annotations

import base64
import html
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime, parseaddr
from typing import Any, Protocol, Sequence

from app.core.config import Settings
from app.core.config import APPROVED_GMAIL_LABEL_NAME


GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
_HTML_TAG_RE = re.compile(r"<[^>]+>")
MAX_MIME_BODY_BYTES = 1_000_000
MAX_PROVIDER_MESSAGE_BYTES = MAX_MIME_BODY_BYTES
MAX_MIME_PARTS = 100
MAX_MIME_DEPTH = 10


@dataclass
class _MimeBudget:
    decoded_bytes: int = 0
    part_count: int = 0


class GmailAdapterError(RuntimeError):
    """Safe adapter failure with a stable category and no payload details."""

    def __init__(self, category: str) -> None:
        self.category = category
        super().__init__(category)


@dataclass(frozen=True)
class NormalizedEmail:
    """Normalized Gmail data passed into deterministic intake processing.

    ``body_text`` is intentionally excluded from repr/logging. M2 keeps it in
    the adapter boundary only; a later minimization step decides what, if any,
    excerpt may be persisted or sent to an LLM.
    """

    provider_message_id: str
    provider_thread_id: str
    sender_email: str
    sender_name: str | None
    received_at: datetime
    subject: str | None
    label_names: tuple[str, ...]
    is_auto_reply: bool
    body_text: str | None = field(default=None, repr=False)


@dataclass(frozen=True)
class GmailPage:
    """One bounded provider page and its provider cursor."""

    messages: tuple[NormalizedEmail, ...]
    next_cursor: str | None


class GmailAdapter(Protocol):
    """Minimal boundary required by the polling service."""

    def list_messages(self, *, label_name: str, cursor: str | None) -> GmailPage:
        """Return one page restricted to the requested label."""


def _decode_body(data: str) -> str:
    try:
        decoded = base64.urlsafe_b64decode(data + ("=" * (-len(data) % 4)))
        return decoded.decode("utf-8", errors="replace")
    except (ValueError, UnicodeError):
        raise GmailAdapterError("invalid_body_encoding") from None


def _walk_body_parts(
    part: dict[str, Any],
    plain_parts: list[str],
    html_parts: list[str],
    *,
    depth: int,
    budget: _MimeBudget,
) -> None:
    if depth > MAX_MIME_DEPTH:
        raise GmailAdapterError("mime_depth_exceeded")
    budget.part_count += 1
    if budget.part_count > MAX_MIME_PARTS:
        raise GmailAdapterError("mime_part_limit_exceeded")

    mime_type = str(part.get("mimeType", "")).lower()
    body = part.get("body") or {}
    data = body.get("data")
    if data:
        encoded = str(data)
        remaining_bytes = MAX_MIME_BODY_BYTES - budget.decoded_bytes
        if len(encoded) > ((remaining_bytes * 4) // 3) + 4:
            raise GmailAdapterError("mime_body_too_large")
        decoded = _decode_body(encoded)
        budget.decoded_bytes += len(decoded.encode("utf-8"))
        if budget.decoded_bytes > MAX_MIME_BODY_BYTES:
            raise GmailAdapterError("mime_body_too_large")
        if mime_type == "text/plain":
            plain_parts.append(decoded)
        elif mime_type == "text/html":
            html_parts.append(decoded)

    children = part.get("parts") or []
    if len(children) > MAX_MIME_PARTS:
        raise GmailAdapterError("mime_part_limit_exceeded")
    for child in children:
        if isinstance(child, dict):
            _walk_body_parts(
                child,
                plain_parts,
                html_parts,
                depth=depth + 1,
                budget=budget,
            )


def extract_text_body(payload: dict[str, Any]) -> str | None:
    """Extract text/plain, or a minimally stripped HTML fallback, without executing it."""

    plain_parts: list[str] = []
    html_parts: list[str] = []
    _walk_body_parts(
        payload,
        plain_parts,
        html_parts,
        depth=0,
        budget=_MimeBudget(),
    )
    if plain_parts:
        return "\n\n".join(part.strip() for part in plain_parts if part.strip()) or None
    if html_parts:
        text = _HTML_TAG_RE.sub(" ", " ".join(html_parts))
        return html.unescape(text).strip() or None
    return None


def _header_map(payload: dict[str, Any]) -> dict[str, str]:
    headers = payload.get("headers") or []
    result: dict[str, str] = {}
    for header in headers:
        if not isinstance(header, dict):
            continue
        name = str(header.get("name", "")).strip().lower()
        value = str(header.get("value", "")).strip()
        if name and name not in result:
            result[name] = value
    return result


def _received_at(payload: dict[str, Any], headers: dict[str, str]) -> datetime:
    internal_date = payload.get("internalDate")
    if internal_date:
        try:
            return datetime.fromtimestamp(int(internal_date) / 1000, tz=timezone.utc)
        except (TypeError, ValueError, OverflowError):
            raise GmailAdapterError("invalid_received_timestamp") from None

    date_header = headers.get("date")
    if date_header:
        try:
            parsed = parsedate_to_datetime(date_header)
            return (parsed or datetime.now(timezone.utc)).astimezone(timezone.utc)
        except (TypeError, ValueError, OverflowError):
            raise GmailAdapterError("invalid_date_header") from None

    raise GmailAdapterError("missing_received_timestamp")


def _is_auto_reply(headers: dict[str, str]) -> bool:
    auto_submitted = headers.get("auto-submitted", "").lower()
    precedence = headers.get("precedence", "").lower()
    response_suppress = headers.get("x-auto-response-suppress", "").lower()
    return (
        bool(auto_submitted and auto_submitted != "no")
        or precedence in {"bulk", "list", "junk"}
        or bool(response_suppress and response_suppress != "none")
    )


def normalize_gmail_message(
    payload: dict[str, Any], *, label_names: Sequence[str]
) -> NormalizedEmail:
    """Convert a Gmail API full message into safe normalized input data."""

    provider_message_id = str(payload.get("id", "")).strip()
    provider_thread_id = str(payload.get("threadId", "")).strip()
    if not provider_message_id or not provider_thread_id:
        raise GmailAdapterError("missing_provider_identity")

    headers = _header_map(payload.get("payload") or {})
    sender_name, sender_email = parseaddr(headers.get("from", ""))
    sender_email = sender_email.strip().lower()
    if not sender_email or "@" not in sender_email:
        raise GmailAdapterError("missing_sender_email")

    subject = headers.get("subject") or None
    body_text = extract_text_body(payload.get("payload") or {})
    return NormalizedEmail(
        provider_message_id=provider_message_id,
        provider_thread_id=provider_thread_id,
        sender_email=sender_email,
        sender_name=sender_name.strip() or None,
        received_at=_received_at(payload, headers),
        subject=subject,
        label_names=tuple(label_names),
        is_auto_reply=_is_auto_reply(headers),
        body_text=body_text,
    )


class MockGmailAdapter:
    """Deterministic page adapter for unit and isolated integration tests."""

    def __init__(self, pages: Sequence[GmailPage]) -> None:
        self._pages = tuple(pages)
        self.calls: list[tuple[str, str | None]] = []

    def list_messages(self, *, label_name: str, cursor: str | None) -> GmailPage:
        self.calls.append((label_name, cursor))
        page_index = int(cursor) if cursor is not None else 0
        if page_index >= len(self._pages):
            return GmailPage(messages=(), next_cursor=None)
        return self._pages[page_index]


class LiveGmailAdapter:
    """Least-privilege Gmail API adapter for the approved mailbox."""

    def __init__(self, settings: Settings, service: Any | None = None) -> None:
        self._settings = settings
        self._service = service or self._build_service(settings)
        self._label_ids: dict[str, str] = {}
        self._identity_verified = False

    @staticmethod
    def _build_service(settings: Settings) -> Any:
        try:
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build

            credentials = Credentials(
                token=None,
                refresh_token=settings.gmail_oauth_refresh_token.get_secret_value(),
                token_uri="https://oauth2.googleapis.com/token",
                client_id=settings.gmail_oauth_client_id.get_secret_value(),
                client_secret=settings.gmail_oauth_client_secret.get_secret_value(),
                scopes=[GMAIL_READONLY_SCOPE],
            )
            return build("gmail", "v1", credentials=credentials, cache_discovery=False)
        except GmailAdapterError:
            raise
        except Exception:
            raise GmailAdapterError("gmail_client_initialization_failed") from None

    def _get_label_id(self, label_name: str) -> str:
        if label_name in self._label_ids:
            return self._label_ids[label_name]
        try:
            labels = self._service.users().labels().list(userId="me").execute().get("labels", [])
        except Exception:
            raise GmailAdapterError("label_lookup_failed") from None
        for label in labels:
            if label.get("name") == label_name and label.get("id"):
                self._label_ids[label_name] = str(label["id"])
                return self._label_ids[label_name]
        raise GmailAdapterError("label_not_found")

    def _verify_mailbox_identity(self) -> None:
        if self._identity_verified:
            return
        try:
            profile = self._service.users().getProfile(userId="me").execute()
            authenticated_address = str(profile.get("emailAddress", "")).strip().lower()
        except Exception:
            raise GmailAdapterError("mailbox_identity_verification_failed") from None

        expected_address = (self._settings.gmail_mailbox_address or "").strip().lower()
        if not authenticated_address or authenticated_address != expected_address:
            raise GmailAdapterError("mailbox_identity_mismatch")
        self._identity_verified = True

    def list_messages(self, *, label_name: str, cursor: str | None) -> GmailPage:
        if label_name != APPROVED_GMAIL_LABEL_NAME:
            raise GmailAdapterError("unapproved_gmail_label")
        self._verify_mailbox_identity()
        label_id = self._get_label_id(label_name)
        try:
            response = (
                self._service.users()
                .messages()
                .list(
                    userId="me",
                    labelIds=[label_id],
                    pageToken=cursor,
                    maxResults=100,
                )
                .execute()
            )
            summaries = response.get("messages", [])
            messages: list[NormalizedEmail] = []
            for summary in summaries:
                message_id = summary.get("id")
                if not message_id:
                    raise GmailAdapterError("missing_provider_identity")
                metadata = (
                    self._service.users()
                    .messages()
                    .get(
                        userId="me",
                        id=message_id,
                        format="metadata",
                        fields="id,threadId,sizeEstimate",
                    )
                    .execute()
                )
                raw_size_estimate = metadata.get("sizeEstimate")
                if raw_size_estimate is None:
                    raise GmailAdapterError("missing_provider_size_estimate")
                try:
                    size_estimate = int(raw_size_estimate)
                except (TypeError, ValueError):
                    raise GmailAdapterError("invalid_provider_size_estimate") from None
                if size_estimate < 0:
                    raise GmailAdapterError("invalid_provider_size_estimate")
                if size_estimate > MAX_PROVIDER_MESSAGE_BYTES:
                    raise GmailAdapterError("provider_message_size_exceeded")
                payload = (
                    self._service.users()
                    .messages()
                    .get(
                        userId="me",
                        id=message_id,
                        format="full",
                        fields="id,threadId,internalDate,payload",
                    )
                    .execute()
                )
                messages.append(normalize_gmail_message(payload, label_names=[label_name]))
            return GmailPage(
                messages=tuple(messages),
                next_cursor=response.get("nextPageToken"),
            )
        except GmailAdapterError:
            raise
        except Exception:
            raise GmailAdapterError("message_fetch_failed") from None
