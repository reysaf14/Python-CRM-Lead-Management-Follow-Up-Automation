"""Deterministic Gmail intake polling and safe checkpoint persistence."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
import re
from typing import Callable

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.gmail.client import GmailAdapter, GmailAdapterError, GmailPage, NormalizedEmail
from app.persistence.base import utc_now
from app.persistence.database import session_scope
from app.persistence.models import Contact, Conversation, Lead, MailboxSyncState, Message
from app.services.extraction import ExtractionOutcome, LeadExtractionService


_EXPLICIT_NON_MATERIAL_RE = re.compile(
    r"\bno\s+(?:new\s+)?(?:question|request|sales\s+information)\b"
    r"|\bno\s+(?:further|additional|more)\s+(?:questions?|requests?|information)\b",
    re.IGNORECASE,
)
_ACKNOWLEDGEMENT_SUBJECT_RE = re.compile(
    r"^\s*(?:re:\s*)?(?:thanks|thank\s+you)\b.*\b(?:update|message|email|reply)\b",
    re.IGNORECASE,
)
_INQUIRY_SIGNAL_RE = re.compile(
    r"\b(?:need|looking\s+for|interested|want|would\s+like|inquir(?:y|e|ies)|"
    r"quote|pricing|budget|proposal|service|automation|project|schedule|book|"
    r"demo|call|help)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PollResult:
    """Sanitized outcome of one bounded polling page."""

    fetched_count: int = 0
    created_message_count: int = 0
    accepted_count: int = 0
    duplicate_count: int = 0
    excluded_count: int = 0
    lead_created_count: int = 0
    extraction_succeeded_count: int = 0
    extraction_manual_review_count: int = 0
    extraction_failed_count: int = 0
    previous_cursor: str | None = None
    next_cursor: str | None = None
    error_category: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.error_category is None


class GmailPollingService:
    """Poll Gmail outside DB transactions and commit one page atomically."""

    def __init__(
        self,
        *,
        adapter: GmailAdapter,
        session_factory: sessionmaker[Session],
        mailbox_key: str,
        label_name: str,
        extraction_service: LeadExtractionService | None = None,
        now_factory: Callable[[], datetime] = utc_now,
    ) -> None:
        self._adapter = adapter
        self._session_factory = session_factory
        self._mailbox_key = mailbox_key
        self._label_name = label_name
        self._extraction_service = extraction_service
        self._now_factory = now_factory

    def poll_once(self) -> PollResult:
        """Fetch one Gmail page and persist it without advancing a failed checkpoint."""

        try:
            previous_cursor = self._read_cursor()
        except SQLAlchemyError:
            return PollResult(error_category="database_read_failed")
        try:
            page = self._adapter.list_messages(
                label_name=self._label_name,
                cursor=previous_cursor,
            )
        except GmailAdapterError as error:
            try:
                self._record_provider_failure(error.category)
            except SQLAlchemyError:
                return PollResult(
                    previous_cursor=previous_cursor,
                    error_category="database_write_failed",
                )
            return PollResult(previous_cursor=previous_cursor, error_category=error.category)

        try:
            result, accepted_messages = self._persist_page(
                page=page,
                previous_cursor=previous_cursor,
            )
        except SQLAlchemyError:
            # session_scope has already rolled back the page and checkpoint.
            return PollResult(
                fetched_count=len(page.messages),
                previous_cursor=previous_cursor,
                error_category="database_write_failed",
            )

        if self._extraction_service is None or not accepted_messages:
            return result
        return self._run_extraction(result, accepted_messages)

    def _read_cursor(self) -> str | None:
        with session_scope(self._session_factory) as session:
            state = session.scalar(
                select(MailboxSyncState).where(
                    MailboxSyncState.mailbox_key == self._mailbox_key
                )
            )
            if state is None:
                state = MailboxSyncState(
                    mailbox_key=self._mailbox_key,
                    label_name=self._label_name,
                    state="ready",
                )
                session.add(state)
                session.flush()
            return state.last_successful_cursor

    def _record_provider_failure(self, category: str) -> None:
        with session_scope(self._session_factory) as session:
            state = session.scalar(
                select(MailboxSyncState).where(
                    MailboxSyncState.mailbox_key == self._mailbox_key
                )
            )
            if state is None:
                state = MailboxSyncState(
                    mailbox_key=self._mailbox_key,
                    label_name=self._label_name,
                    state="error",
                    error_category=category,
                )
                session.add(state)
            else:
                state.state = "error"
                state.error_category = category

    def _persist_page(
        self,
        *,
        page: GmailPage,
        previous_cursor: str | None,
    ) -> tuple[PollResult, tuple[NormalizedEmail, ...]]:
        created_message_count = 0
        accepted_count = 0
        duplicate_count = 0
        excluded_count = 0
        lead_created_count = 0
        accepted_messages: list[NormalizedEmail] = []

        with session_scope(self._session_factory) as session:
            state = session.scalar(
                select(MailboxSyncState).where(
                    MailboxSyncState.mailbox_key == self._mailbox_key
                )
            )
            if state is None:
                state = MailboxSyncState(
                    mailbox_key=self._mailbox_key,
                    label_name=self._label_name,
                    state="ready",
                )
                session.add(state)
                session.flush()

            for normalized in page.messages:
                if self._label_name not in normalized.label_names:
                    excluded_count += 1
                    continue

                existing = session.scalar(
                    select(Message).where(
                        Message.provider_message_id == normalized.provider_message_id
                    )
                )
                if existing is not None:
                    duplicate_count += 1
                    continue

                if normalized.is_auto_reply:
                    session.add(
                        self._excluded_message(
                            normalized,
                            is_auto_reply=True,
                        )
                    )
                    created_message_count += 1
                    excluded_count += 1
                    continue

                if self._is_clearly_irrelevant(normalized):
                    session.add(self._excluded_message(normalized, is_auto_reply=False))
                    created_message_count += 1
                    excluded_count += 1
                    continue

                message, lead_created = self._accepted_message(session, normalized)
                session.add(message)
                created_message_count += 1
                accepted_count += 1
                lead_created_count += int(lead_created)
                accepted_messages.append(normalized)

            state.last_successful_cursor = page.next_cursor
            state.last_successful_sync_at = self._now_factory()
            state.state = "ready"
            state.error_category = None

        return (
            PollResult(
                fetched_count=len(page.messages),
                created_message_count=created_message_count,
                accepted_count=accepted_count,
                duplicate_count=duplicate_count,
                excluded_count=excluded_count,
                lead_created_count=lead_created_count,
                previous_cursor=previous_cursor,
                next_cursor=page.next_cursor,
            ),
            tuple(accepted_messages),
        )

    def _run_extraction(
        self,
        result: PollResult,
        accepted_messages: tuple[NormalizedEmail, ...],
    ) -> PollResult:
        succeeded = 0
        manual_review = 0
        failed = 0
        assert self._extraction_service is not None
        for normalized in accepted_messages:
            outcome: ExtractionOutcome = self._extraction_service.process_normalized_email(
                normalized
            )
            if outcome.status == "succeeded":
                succeeded += 1
            elif outcome.status == "manual_review":
                manual_review += 1
            elif outcome.status == "failed":
                failed += 1
        return replace(
            result,
            extraction_succeeded_count=succeeded,
            extraction_manual_review_count=manual_review,
            extraction_failed_count=failed,
        )

    @staticmethod
    def _is_clearly_irrelevant(normalized: NormalizedEmail) -> bool:
        """Exclude only explicit non-material acknowledgements before extraction.

        This gate is intentionally conservative. A message with an inquiry signal
        remains eligible for extraction; ambiguous content is not silently excluded.
        """

        subject = (normalized.subject or "").strip()
        body = (normalized.body_text or "").strip()
        combined = " ".join(part for part in (subject, body) if part)
        if not combined:
            return False

        if _EXPLICIT_NON_MATERIAL_RE.search(combined):
            return not _INQUIRY_SIGNAL_RE.search(body)

        if _ACKNOWLEDGEMENT_SUBJECT_RE.search(subject):
            return not _INQUIRY_SIGNAL_RE.search(body)

        return False

    @staticmethod
    def _excluded_message(
        normalized: NormalizedEmail,
        *,
        is_auto_reply: bool,
    ) -> Message:
        return Message(
            provider_message_id=normalized.provider_message_id,
            provider_thread_id=normalized.provider_thread_id,
            sender_email=normalized.sender_email,
            sender_name=normalized.sender_name,
            received_at=normalized.received_at,
            subject=normalized.subject,
            processing_state="excluded",
            is_auto_reply=is_auto_reply,
            is_relevant=False,
            # The unbounded adapter body is never persisted by M2.
            content_excerpt=None,
        )

    @staticmethod
    def _accepted_message(session: Session, normalized: NormalizedEmail) -> tuple[Message, bool]:
        contact = session.scalar(
            select(Contact).where(Contact.email_normalized == normalized.sender_email)
        )
        if contact is None:
            contact = Contact(
                email_normalized=normalized.sender_email,
                display_name=normalized.sender_name,
            )
            session.add(contact)
            session.flush()

        conversation = session.scalar(
            select(Conversation).where(
                Conversation.provider_thread_id == normalized.provider_thread_id
            )
        )
        if conversation is None:
            conversation = Conversation(
                provider_thread_id=normalized.provider_thread_id,
                contact_id=contact.id,
                subject=normalized.subject,
            )
            session.add(conversation)
            session.flush()

        lead = session.scalar(
            select(Lead).where(Lead.conversation_id == conversation.id)
        )
        lead_created = False
        if lead is None:
            lead = Lead(
                contact_id=conversation.contact_id,
                conversation_id=conversation.id,
                status="Pending Extraction",
            )
            session.add(lead)
            session.flush()
            lead_created = True

        return (
            Message(
                provider_message_id=normalized.provider_message_id,
                provider_thread_id=normalized.provider_thread_id,
                conversation_id=conversation.id,
                lead_id=lead.id,
                sender_email=normalized.sender_email,
                sender_name=normalized.sender_name,
                received_at=normalized.received_at,
                subject=normalized.subject,
                processing_state="pending_extraction",
                is_auto_reply=False,
                is_relevant=None,
                # M3 owns minimization and controlled excerpt persistence.
                content_excerpt=None,
            ),
            lead_created,
        )
