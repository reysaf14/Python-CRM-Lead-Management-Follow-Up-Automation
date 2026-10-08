from datetime import datetime, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.adapters.gmail.client import GmailAdapterError, GmailPage, MockGmailAdapter, NormalizedEmail
from app.persistence.base import Base
from app.persistence.database import build_session_factory
from app.persistence.models import Conversation, Lead, MailboxSyncState, Message
from app.services.gmail_polling import GmailPollingService


def _message(
    message_id: str,
    thread_id: str,
    *,
    labels: tuple[str, ...] = ("Sales Leads",),
    auto_reply: bool = False,
    sender: str = "prospect@example.invalid",
) -> NormalizedEmail:
    return NormalizedEmail(
        provider_message_id=message_id,
        provider_thread_id=thread_id,
        sender_email=sender,
        sender_name="Synthetic Prospect",
        received_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        subject="Synthetic sales inquiry",
        label_names=labels,
        is_auto_reply=auto_reply,
        body_text="Untrusted synthetic email body.",
    )


def _service(adapter: MockGmailAdapter):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine, GmailPollingService(
        adapter=adapter,
        session_factory=build_session_factory(engine),
        mailbox_key="synthetic-mailbox",
        label_name="Sales Leads",
    )


def test_polling_filters_deduplicates_and_preserves_thread_continuity() -> None:
    adapter = MockGmailAdapter(
        [
            GmailPage(
                messages=(
                    _message("message-001", "thread-001"),
                    _message("message-unlabeled", "thread-unlabeled", labels=("Other",)),
                    _message("message-auto", "thread-auto", auto_reply=True),
                ),
                next_cursor="1",
            ),
            GmailPage(
                messages=(
                    _message("message-001", "thread-001"),
                    _message("message-002", "thread-001"),
                ),
                next_cursor=None,
            ),
        ]
    )
    engine, service = _service(adapter)

    try:
        first = service.poll_once()
        assert first.fetched_count == 3
        assert first.created_message_count == 2
        assert first.accepted_count == 1
        assert first.duplicate_count == 0
        assert first.excluded_count == 2
        assert first.lead_created_count == 1
        assert first.next_cursor == "1"

        second = service.poll_once()
        assert second.fetched_count == 2
        assert second.created_message_count == 1
        assert second.accepted_count == 1
        assert second.duplicate_count == 1
        assert second.lead_created_count == 0
        assert second.next_cursor is None

        with Session(engine) as session:
            assert session.scalar(select(Conversation.id)) is not None
            assert session.scalar(select(Lead.status)) == "Pending Extraction"
            stored_messages = session.scalars(select(Message)).all()
            assert len(stored_messages) == 3
            assert all(message.content_excerpt is None for message in stored_messages)
            sync_state = session.scalar(select(MailboxSyncState))
            assert sync_state is not None
            assert sync_state.last_successful_cursor is None
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


class FailingAdapter:
    def list_messages(self, *, label_name: str, cursor: str | None) -> GmailPage:
        raise GmailAdapterError("provider_timeout")


def test_provider_failure_does_not_advance_checkpoint() -> None:
    adapter = MockGmailAdapter([GmailPage(messages=(), next_cursor="stored")])
    engine, service = _service(adapter)

    try:
        first = service.poll_once()
        assert first.succeeded

        failing_service = GmailPollingService(
            adapter=FailingAdapter(),
            session_factory=build_session_factory(engine),
            mailbox_key="synthetic-mailbox",
            label_name="Sales Leads",
        )
        failure = failing_service.poll_once()

        assert failure.error_category == "provider_timeout"
        with Session(engine) as session:
            sync_state = session.scalar(select(MailboxSyncState))
            assert sync_state is not None
            assert sync_state.last_successful_cursor == "stored"
            assert sync_state.state == "error"
            assert sync_state.error_category == "provider_timeout"
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()
