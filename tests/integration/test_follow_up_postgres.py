import os
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.domain.scoring import DEFAULT_SCORING_RULES
from app.persistence.base import Base
from app.persistence.models import Activity, Contact, Conversation, Lead, Message, Reminder
from app.services.follow_up import FollowUpSchedulerService, SalesResponseService
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


def test_postgres_follow_up_is_sales_only_and_idempotent(postgres_engine) -> None:
    factory = sessionmaker(bind=postgres_engine, expire_on_commit=False)
    qualifying_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
    with Session(postgres_engine) as session:
        contact = Contact(email_normalized="follow-up-postgres@example.invalid")
        session.add(contact)
        session.flush()
        conversation = Conversation(
            provider_thread_id="thread-follow-up-postgres",
            contact_id=contact.id,
            subject="Synthetic follow-up inquiry",
        )
        session.add(conversation)
        session.flush()
        lead = Lead(
            contact_id=contact.id,
            conversation_id=conversation.id,
            status="New",
        )
        session.add(lead)
        session.commit()
        lead_id = lead.id

    scoring = LeadScoringService(session_factory=factory, rules=DEFAULT_SCORING_RULES)
    with Session(postgres_engine) as session:
        lead = session.get(Lead, lead_id)
        assert lead is not None
        message = Message(
            provider_message_id="message-follow-up-postgres",
            provider_thread_id="thread-follow-up-postgres",
            conversation_id=lead.conversation_id,
            lead_id=lead.id,
            sender_email="follow-up-postgres@example.invalid",
            received_at=qualifying_at,
            subject="Synthetic follow-up inquiry",
            processing_state="extraction_succeeded",
        )
        session.add(message)
        session.commit()
        message_id = message.id

    assert scoring.score_lead(
        lead_id=lead_id,
        source_message_id=message_id,
        facts={
            "intent": "sales_inquiry",
            "service_interest": "Customer Support Automation",
            "stated_budget": "$1,500",
            "business_summary": "Synthetic online store inquiry",
        },
    ).priority == "High"

    due_now = qualifying_at + timedelta(hours=24)
    scheduler = FollowUpSchedulerService(
        session_factory=factory,
        now_factory=lambda: due_now,
    )
    first = scheduler.scan_once()
    second = scheduler.scan_once()
    assert first.reminder_created_count == 1
    assert second.reminder_created_count == 0

    response = SalesResponseService(
        session_factory=factory,
        now_factory=lambda: due_now + timedelta(minutes=1),
    ).record_response(
        lead_id=lead_id,
        correlation_id="sales-response:postgres:001",
    )
    assert response.status == "recorded"
    assert response.suppressed_reminder_count == 1

    with Session(postgres_engine) as session:
        reminder = session.scalar(select(Reminder))
        reminder_activity = session.scalar(
            select(Activity).where(Activity.activity_type == "follow_up_reminder")
        )
        assert reminder is not None
        assert reminder.status == "suppressed"
        assert reminder_activity is not None
        assert reminder_activity.safe_metadata == {
            "destination": "sales",
            "reminder_type": "high_priority_follow_up",
        }
