import os
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.domain.scoring import DEFAULT_SCORING_RULES
from app.persistence.base import Base
from app.persistence.models import Contact, Conversation, Lead, Message, ScoreEvaluation
from app.services.scoring import LeadScoringService


pytestmark = pytest.mark.postgres


@pytest.fixture(scope="module")
def postgres_engine():
    database_url = os.getenv("M1_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Set M1_TEST_DATABASE_URL to run the isolated PostgreSQL integration tests")

    engine = create_engine(database_url, pool_pre_ping=True)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_postgres_scoring_persists_version_and_is_idempotent(postgres_engine) -> None:
    factory = sessionmaker(bind=postgres_engine, expire_on_commit=False)
    with Session(postgres_engine) as session:
        contact = Contact(email_normalized="score@example.invalid")
        session.add(contact)
        session.flush()
        conversation = Conversation(
            provider_thread_id="thread-score-postgres",
            contact_id=contact.id,
            subject="Synthetic scoring inquiry",
        )
        session.add(conversation)
        session.flush()
        lead = Lead(contact_id=contact.id, conversation_id=conversation.id, status="New")
        session.add(lead)
        session.flush()
        message = Message(
            provider_message_id="message-score-postgres",
            provider_thread_id=conversation.provider_thread_id,
            conversation_id=conversation.id,
            lead_id=lead.id,
            sender_email=contact.email_normalized,
            received_at=datetime.now(timezone.utc),
            subject="Synthetic scoring inquiry",
            processing_state="extraction_succeeded",
        )
        session.add(message)
        session.commit()
        lead_id = lead.id
        message_id = message.id

    service = LeadScoringService(session_factory=factory, rules=DEFAULT_SCORING_RULES)
    facts = {
        "intent": "sales_inquiry",
        "service_interest": "Customer Support Automation",
        "stated_budget": "$1,500",
        "business_summary": "Synthetic online store inquiry",
    }

    first = service.score_lead(lead_id=lead_id, source_message_id=message_id, facts=facts)
    second = service.score_lead(lead_id=lead_id, source_message_id=message_id, facts=facts)

    assert first.status == "scored"
    assert first.priority == "High"
    assert second.status == "already_scored"
    with Session(postgres_engine) as session:
        lead = session.get(Lead, lead_id)
        assert lead is not None
        assert lead.priority == "High"
        assert session.scalar(select(ScoreEvaluation.id)) is not None
        assert len(session.scalars(select(ScoreEvaluation)).all()) == 1
