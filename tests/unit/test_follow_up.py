from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.domain.scoring import DEFAULT_SCORING_RULES
from app.persistence.base import Base
from app.persistence.database import build_session_factory
from app.persistence.models import (
    Activity,
    Contact,
    Conversation,
    Lead,
    Message,
    Reminder,
)
from app.services.follow_up import (
    HIGH_FOLLOW_UP_REMINDER_TYPE,
    FollowUpSchedulerService,
    SalesResponseService,
)
from app.services.scoring import LeadScoringService


QUALIFYING_AT = datetime(2025, 1, 1, tzinfo=timezone.utc)


def _build_high_lead() -> tuple[object, object, int]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = build_session_factory(engine)

    with Session(engine) as session:
        contact = Contact(email_normalized="follow-up@example.invalid")
        session.add(contact)
        session.flush()
        conversation = Conversation(
            provider_thread_id="thread-follow-up-001",
            contact_id=contact.id,
            subject="Synthetic follow-up inquiry",
        )
        session.add(conversation)
        session.flush()
        lead = Lead(
            contact_id=contact.id,
            conversation_id=conversation.id,
            status="New",
            priority="High",
            score=100,
        )
        session.add(lead)
        session.flush()
        message = Message(
            provider_message_id="message-follow-up-001",
            provider_thread_id=conversation.provider_thread_id,
            conversation_id=conversation.id,
            lead_id=lead.id,
            sender_email=contact.email_normalized,
            received_at=QUALIFYING_AT,
            subject="Synthetic follow-up inquiry",
            processing_state="extraction_succeeded",
        )
        session.add(message)
        session.commit()

        scoring = LeadScoringService(
            session_factory=session_factory,
            rules=DEFAULT_SCORING_RULES,
        )
        outcome = scoring.score_lead(
            lead_id=lead.id,
            source_message_id=message.id,
            facts={
                "intent": "sales_inquiry",
                "service_interest": "Customer Support Automation",
                "stated_budget": "$1,500",
                "business_summary": "Synthetic online store inquiry",
            },
        )
        assert outcome.priority == "High"
        return engine, session_factory, lead.id


def test_due_high_lead_creates_one_sales_reminder_and_repeated_scan_is_idempotent() -> None:
    engine, session_factory, lead_id = _build_high_lead()
    try:
        now = QUALIFYING_AT + timedelta(hours=24)
        scheduler = FollowUpSchedulerService(
            session_factory=session_factory,
            now_factory=lambda: now,
        )

        first = scheduler.scan_once()
        second = scheduler.scan_once()

        assert first.reminder_created_count == 1
        assert second.reminder_created_count == 0
        assert second.reminder_existing_count == 1
        with Session(engine) as session:
            reminders = list(session.scalars(select(Reminder)))
            activities = list(session.scalars(select(Activity)))
            assert len(reminders) == 1
            assert reminders[0].status == "due"
            assert reminders[0].reminder_type == HIGH_FOLLOW_UP_REMINDER_TYPE
            assert len(activities) == 1
            assert activities[0].activity_type == "follow_up_reminder"
            assert activities[0].safe_metadata == {
                "destination": "sales",
                "reminder_type": HIGH_FOLLOW_UP_REMINDER_TYPE,
            }
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_not_due_high_lead_does_not_create_reminder() -> None:
    engine, session_factory, _lead_id = _build_high_lead()
    try:
        scheduler = FollowUpSchedulerService(
            session_factory=session_factory,
            now_factory=lambda: QUALIFYING_AT + timedelta(hours=23),
        )

        result = scheduler.scan_once()

        assert result.scanned_high_lead_count == 1
        assert result.not_due_count == 1
        with Session(engine) as session:
            assert session.scalar(select(Reminder.id)) is None
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_record_response_suppresses_due_reminder_and_is_idempotent() -> None:
    engine, session_factory, lead_id = _build_high_lead()
    try:
        due_now = QUALIFYING_AT + timedelta(hours=24)
        scheduler = FollowUpSchedulerService(
            session_factory=session_factory,
            now_factory=lambda: due_now,
        )
        assert scheduler.scan_once().reminder_created_count == 1

        response_service = SalesResponseService(
            session_factory=session_factory,
            now_factory=lambda: due_now + timedelta(minutes=5),
        )
        first = response_service.record_response(
            lead_id=lead_id,
            correlation_id="sales-response:lead-1:001",
        )
        second = response_service.record_response(
            lead_id=lead_id,
            correlation_id="sales-response:lead-1:001",
        )

        assert first.status == "recorded"
        assert first.suppressed_reminder_count == 1
        assert second.status == "already_recorded"
        with Session(engine) as session:
            reminder = session.scalar(select(Reminder))
            lead = session.get(Lead, lead_id)
            response = session.scalar(
                select(Activity).where(Activity.activity_type == "sales_response")
            )
            assert reminder is not None
            assert reminder.status == "suppressed"
            assert lead is not None
            assert lead.next_follow_up_at is None
            assert response is not None
            assert response.status == "completed"

        after_response = scheduler.scan_once()
        assert after_response.reminder_created_count == 0
        assert after_response.reminder_suppressed_count == 0
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_medium_lead_is_not_scanned_for_high_follow_up() -> None:
    engine, session_factory, lead_id = _build_high_lead()
    try:
        with Session(engine) as session:
            lead = session.get(Lead, lead_id)
            assert lead is not None
            lead.priority = "Medium"
            session.commit()

        scheduler = FollowUpSchedulerService(
            session_factory=session_factory,
            now_factory=lambda: QUALIFYING_AT + timedelta(hours=48),
        )
        result = scheduler.scan_once()

        assert result.scanned_high_lead_count == 0
        assert result.reminder_created_count == 0
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()
