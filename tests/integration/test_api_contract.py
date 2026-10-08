from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_crm_session_factory, get_db_session
from app.api.main import create_app
from app.persistence.base import Base
from app.persistence.database import build_session_factory
from app.persistence.models import (
    Activity,
    Contact,
    Conversation,
    ExtractionAttempt,
    Lead,
    Message,
    Reminder,
)


@pytest.fixture
def api_context():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = build_session_factory(engine)
    now = datetime(2025, 1, 2, tzinfo=timezone.utc)

    with Session(engine) as session:
        contact = Contact(
            email_normalized="api-prospect@example.invalid",
            display_name="Synthetic Prospect",
            company_name="Synthetic Store",
        )
        session.add(contact)
        session.flush()
        conversation = Conversation(
            provider_thread_id="thread-api-001",
            contact_id=contact.id,
            subject="Customer support automation inquiry",
        )
        session.add(conversation)
        session.flush()
        lead = Lead(
            contact_id=contact.id,
            conversation_id=conversation.id,
            status="New",
            priority="High",
            score=100,
            score_reason="Synthetic scoring explanation",
            next_follow_up_at=now,
        )
        session.add(lead)
        session.flush()
        message = Message(
            provider_message_id="message-api-001",
            provider_thread_id=conversation.provider_thread_id,
            conversation_id=conversation.id,
            lead_id=lead.id,
            sender_email=contact.email_normalized,
            received_at=now - timedelta(hours=24),
            subject=conversation.subject,
            content_excerpt="Bounded synthetic excerpt.",
            processing_state="extraction_succeeded",
        )
        session.add(message)
        session.flush()
        session.add(
            ExtractionAttempt(
                message_id=message.id,
                lead_id=lead.id,
                extraction_policy_version="synthetic-api-v1",
                attempt_number=1,
                status="succeeded",
                requested_at=now - timedelta(hours=24),
                completed_at=now - timedelta(hours=23, minutes=59),
                result_payload={
                    "intent": "sales_inquiry",
                    "service_interest": "Customer Support Automation",
                    "stated_budget": "$1,500",
                    "business_summary": "Synthetic store inquiry",
                },
            )
        )
        reminder = Reminder(
            lead_id=lead.id,
            reminder_type="high_priority_follow_up",
            due_at=now - timedelta(minutes=1),
            status="due",
            correlation_id="follow-up:1:001",
            triggered_at=now,
        )
        session.add(reminder)

        review_contact = Contact(email_normalized="review@example.invalid")
        session.add(review_contact)
        session.flush()
        review_conversation = Conversation(
            provider_thread_id="thread-api-review",
            contact_id=review_contact.id,
            subject="Ambiguous synthetic inquiry",
        )
        session.add(review_conversation)
        session.flush()
        review_lead = Lead(
            contact_id=review_contact.id,
            conversation_id=review_conversation.id,
            status="Pending Extraction",
        )
        session.add(review_lead)
        session.flush()
        session.add(
            Message(
                provider_message_id="message-api-review",
                provider_thread_id=review_conversation.provider_thread_id,
                conversation_id=review_conversation.id,
                lead_id=review_lead.id,
                sender_email=review_contact.email_normalized,
                received_at=now,
                subject=review_conversation.subject,
                processing_state="manual_review",
            )
        )
        session.commit()
        lead_id = lead.id

    application = create_app()

    def override_factory():
        return session_factory

    def override_session():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    application.dependency_overrides[get_crm_session_factory] = override_factory
    application.dependency_overrides[get_db_session] = override_session
    client = TestClient(application)
    yield client, engine, lead_id
    application.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_operator_api_exposes_operational_views_without_list_email(api_context) -> None:
    client, engine, lead_id = api_context

    summary = client.get("/api/v1/dashboard/summary")
    leads = client.get("/api/v1/leads", params={"search": "api-prospect@example.invalid"})
    review = client.get("/api/v1/manual-review")
    follow_ups = client.get("/api/v1/follow-ups")

    assert summary.status_code == 200
    assert summary.json() == {
        "new_leads": 1,
        "high_priority_leads": 1,
        "follow_ups_due": 1,
        "pending_extraction_or_manual_review": 1,
    }
    assert leads.status_code == 200
    assert len(leads.json()) == 1
    assert "contact_email" not in leads.json()[0]
    assert review.status_code == 200
    assert len(review.json()) == 1
    assert review.json()[0]["review_state"] == "manual_review"
    assert follow_ups.status_code == 200
    assert follow_ups.json()[0]["lead_id"] == lead_id

    detail = client.get(f"/api/v1/leads/{lead_id}")
    assert detail.status_code == 200
    assert detail.json()["contact_email"] == "api-prospect@example.invalid"
    assert detail.json()["messages"][0]["content_excerpt"] == "Bounded synthetic excerpt."

    with Session(engine) as session:
        assert session.scalar(select(Activity.id)) is None


def test_operator_api_records_response_and_suppresses_reminder(api_context) -> None:
    client, engine, lead_id = api_context

    response = client.post(
        f"/api/v1/leads/{lead_id}/response",
        json={"correlation_id": "api-response:synthetic:001"},
    )
    repeated = client.post(
        f"/api/v1/leads/{lead_id}/response",
        json={"correlation_id": "api-response:synthetic:001"},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "recorded", "suppressed_reminder_count": 1}
    assert repeated.status_code == 200
    assert repeated.json() == {"status": "already_recorded", "suppressed_reminder_count": 0}
    with Session(engine) as session:
        reminder = session.scalar(select(Reminder))
        activity = session.scalar(select(Activity))
        assert reminder is not None
        assert reminder.status == "suppressed"
        assert activity is not None
        assert activity.activity_type == "sales_response"
