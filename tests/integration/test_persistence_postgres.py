import os
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.persistence.base import Base
from app.persistence.database import session_scope
from app.persistence.models import Contact, Conversation, Lead, Message


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
