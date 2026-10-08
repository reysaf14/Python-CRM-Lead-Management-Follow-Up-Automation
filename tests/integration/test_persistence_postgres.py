import os
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.gmail.client import GmailPage, MockGmailAdapter, NormalizedEmail
from app.persistence.base import Base
from app.persistence.database import session_scope
from app.persistence.models import Contact, Conversation, Lead, MailboxSyncState, Message
from app.services.gmail_polling import GmailPollingService


pytestmark = pytest.mark.postgres


@pytest.fixture(scope="module")
def postgres_engine():
    database_url = os.getenv("M1_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Set M1_TEST_DATABASE_URL to run the isolated PostgreSQL integration tests")

    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
        yield engine
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture()
def isolated_session(postgres_engine):
    factory = sessionmaker(bind=postgres_engine, expire_on_commit=False)
    with Session(postgres_engine) as session:
        yield session
        session.rollback()
    Base.metadata.drop_all(postgres_engine)
    Base.metadata.create_all(postgres_engine)


def test_postgres_schema_supports_thread_lead_message_relationships(isolated_session: Session) -> None:
    contact = Contact(email_normalized="lead@example.invalid", display_name="Synthetic Lead")
    isolated_session.add(contact)
    isolated_session.flush()

    conversation = Conversation(
        provider_thread_id="thread-m1-001",
        contact_id=contact.id,
        subject="Synthetic inquiry",
    )
    isolated_session.add(conversation)
    isolated_session.flush()

    lead = Lead(contact_id=contact.id, conversation_id=conversation.id)
    isolated_session.add(lead)
    isolated_session.flush()

    message = Message(
        provider_message_id="message-m1-001",
        provider_thread_id="thread-m1-001",
        conversation_id=conversation.id,
        lead_id=lead.id,
        sender_email=contact.email_normalized,
        received_at=datetime.now(timezone.utc),
        subject="Synthetic inquiry",
        processing_state="received",
    )
    isolated_session.add(message)
    isolated_session.commit()

    stored = isolated_session.scalar(
        select(Message).where(Message.provider_message_id == "message-m1-001")
    )
    assert stored is not None
    assert stored.lead_id == lead.id
    assert stored.conversation_id == conversation.id


def test_postgres_rejects_duplicate_provider_message_identity(isolated_session: Session) -> None:
    values = {
        "provider_message_id": "message-m1-duplicate",
        "provider_thread_id": "thread-m1-duplicate",
        "sender_email": "duplicate@example.invalid",
        "received_at": datetime.now(timezone.utc),
    }
    isolated_session.add(Message(**values))
    isolated_session.commit()

    isolated_session.add(Message(**values))
    with pytest.raises(IntegrityError):
        isolated_session.commit()
    isolated_session.rollback()

    count = isolated_session.scalar(
        select(Message).where(Message.provider_message_id == "message-m1-duplicate")
    )
    assert count is not None


def test_session_scope_rolls_back_postgres_unit_of_work(postgres_engine) -> None:
    factory = sessionmaker(bind=postgres_engine, expire_on_commit=False)

    with pytest.raises(RuntimeError, match="synthetic transaction failure"):
        with session_scope(factory) as session:
            session.add(Contact(email_normalized="transaction@example.invalid"))
            raise RuntimeError("synthetic transaction failure")

    with Session(postgres_engine) as session:
        assert session.scalar(
            select(Contact).where(Contact.email_normalized == "transaction@example.invalid")
        ) is None


class FaultInjectingPollingService(GmailPollingService):
    def __init__(self, *, fail_message_id: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self._fail_message_id = fail_message_id

    def _accepted_message(self, session, normalized):
        if normalized.provider_message_id == self._fail_message_id:
            from sqlalchemy.exc import SQLAlchemyError

            raise SQLAlchemyError("synthetic persist failure")
        return GmailPollingService._accepted_message(session, normalized)


def test_postgres_polling_failure_rolls_back_page_preserves_checkpoint_and_recovers(
    postgres_engine,
) -> None:
    factory = sessionmaker(bind=postgres_engine, expire_on_commit=False)
    first = NormalizedEmail(
        provider_message_id="message-fault-first",
        provider_thread_id="thread-fault-first",
        sender_email="first@example.invalid",
        sender_name="First Synthetic Lead",
        received_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        subject="First synthetic inquiry",
        label_names=("Sales Leads",),
        is_auto_reply=False,
        body_text="We need an automation proposal.",
    )
    second = NormalizedEmail(
        provider_message_id="message-fault-second",
        provider_thread_id="thread-fault-second",
        sender_email="second@example.invalid",
        sender_name="Second Synthetic Lead",
        received_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        subject="Second synthetic inquiry",
        label_names=("Sales Leads",),
        is_auto_reply=False,
        body_text="We need an automation proposal.",
    )
    adapter = MockGmailAdapter(
        [GmailPage(messages=(first, second), next_cursor="1")]
    )

    with Session(postgres_engine) as session:
        session.add(
            MailboxSyncState(
                mailbox_key="fault-injection-mailbox",
                label_name="Sales Leads",
                last_successful_cursor="0",
                state="ready",
            )
        )
        session.commit()

    failing_service = FaultInjectingPollingService(
        adapter=adapter,
        session_factory=factory,
        mailbox_key="fault-injection-mailbox",
        label_name="Sales Leads",
        fail_message_id="message-fault-second",
    )
    failed = failing_service.poll_once()

    assert failed.error_category == "database_write_failed"
    assert failed.previous_cursor == "0"
    assert failed.fetched_count == 2
    with Session(postgres_engine) as session:
        assert session.scalar(select(Contact.id)) is None
        assert session.scalar(select(Conversation.id)) is None
        assert session.scalar(select(Lead.id)) is None
        assert session.scalar(select(Message.id)) is None
        state = session.scalar(
            select(MailboxSyncState).where(
                MailboxSyncState.mailbox_key == "fault-injection-mailbox"
            )
        )
        assert state is not None
        assert state.last_successful_cursor == "0"
        assert state.state == "ready"
        assert state.error_category is None

    recovered_service = GmailPollingService(
        adapter=adapter,
        session_factory=factory,
        mailbox_key="fault-injection-mailbox",
        label_name="Sales Leads",
    )
    recovered = recovered_service.poll_once()

    assert recovered.succeeded
    assert recovered.accepted_count == 2
    assert recovered.created_message_count == 2
    assert recovered.next_cursor == "1"
    with Session(postgres_engine) as session:
        assert session.scalar(select(Contact.id)) is not None
        assert session.scalar(select(Conversation.id)) is not None
        assert session.scalar(select(Lead.id)) is not None
        assert session.scalar(select(Message.id)) is not None
        state = session.scalar(
            select(MailboxSyncState).where(
                MailboxSyncState.mailbox_key == "fault-injection-mailbox"
            )
        )
        assert state is not None
        assert state.last_successful_cursor == "1"
