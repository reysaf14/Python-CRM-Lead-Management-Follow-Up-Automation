"""Read-only CRM views for the internal API and sales dashboard."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from app.persistence.models import (
    Activity,
    Contact,
    Conversation,
    ExtractionAttempt,
    Lead,
    Message,
    Reminder,
    ScoreEvaluation,
)


REVIEW_MESSAGE_STATES = ("pending_extraction", "manual_review")


class CRMViewService:
    """Expose sanitized internal CRM projections without changing domain state."""

    def summary(self, session: Session, *, now: datetime) -> dict[str, int]:
        """Return operational counts only; no customer content is included."""

        new_leads = session.scalar(
            select(func.count(Lead.id)).where(Lead.status == "New")
        ) or 0
        high_priority_leads = session.scalar(
            select(func.count(Lead.id)).where(Lead.priority == "High")
        ) or 0
        follow_ups_due = session.scalar(
            select(func.count(Reminder.id)).where(
                Reminder.status == "due",
                Reminder.due_at <= now,
            )
        ) or 0
        manual_review = session.scalar(
            select(func.count(func.distinct(Message.lead_id))).where(
                Message.lead_id.is_not(None),
                Message.processing_state.in_(REVIEW_MESSAGE_STATES),
            )
        ) or 0
        return {
            "new_leads": int(new_leads),
            "high_priority_leads": int(high_priority_leads),
            "follow_ups_due": int(follow_ups_due),
            "pending_extraction_or_manual_review": int(manual_review),
        }

    def list_leads(
        self,
        session: Session,
        *,
        status: str | None = None,
        priority: str | None = None,
        search: str | None = None,
        review_only: bool = False,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        query: Select[tuple[Lead, Contact, Conversation]] = (
            select(Lead, Contact, Conversation)
            .join(Contact, Contact.id == Lead.contact_id)
            .join(Conversation, Conversation.id == Lead.conversation_id)
            .order_by(Lead.updated_at.desc(), Lead.id.desc())
            .limit(limit)
        )
        if status:
            query = query.where(Lead.status == status)
        if priority:
            query = query.where(Lead.priority == priority)
        if search:
            search_term = f"%{search.strip()}%"
            query = query.where(
                or_(
                    Contact.display_name.ilike(search_term),
                    Contact.company_name.ilike(search_term),
                    Contact.email_normalized.ilike(search_term),
                    Conversation.subject.ilike(search_term),
                )
            )

        rows = session.execute(query).all()
        cards = [self._lead_card(session, lead, contact, conversation) for lead, contact, conversation in rows]
        if review_only:
            return [card for card in cards if card["review_state"] is not None]
        return cards

    def get_lead_detail(self, session: Session, *, lead_id: int) -> dict[str, Any] | None:
        row = session.execute(
            select(Lead, Contact, Conversation)
            .join(Contact, Contact.id == Lead.contact_id)
            .join(Conversation, Conversation.id == Lead.conversation_id)
            .where(Lead.id == lead_id)
        ).first()
        if row is None:
            return None
        lead, contact, conversation = row
        card = self._lead_card(session, lead, contact, conversation)
        messages = session.scalars(
            select(Message)
            .where(Message.lead_id == lead_id)
            .order_by(Message.received_at.asc(), Message.id.asc())
        ).all()
        attempts = session.scalars(
            select(ExtractionAttempt)
            .where(ExtractionAttempt.lead_id == lead_id)
            .order_by(ExtractionAttempt.id.desc())
        ).all()
        evaluations = session.scalars(
            select(ScoreEvaluation)
            .where(ScoreEvaluation.lead_id == lead_id)
            .order_by(ScoreEvaluation.evaluated_at.desc(), ScoreEvaluation.id.desc())
        ).all()
        activities = session.scalars(
            select(Activity)
            .where(Activity.lead_id == lead_id)
            .order_by(Activity.created_at.desc(), Activity.id.desc())
        ).all()
        reminders = session.scalars(
            select(Reminder)
            .where(Reminder.lead_id == lead_id)
            .order_by(Reminder.due_at.desc(), Reminder.id.desc())
        ).all()

        return {
            **card,
            "contact_email": contact.email_normalized,
            "conversation_state": conversation.state,
            "messages": [
                {
                    "id": message.id,
                    "subject": message.subject,
                    "sender_email": message.sender_email,
                    "received_at": message.received_at,
                    "processing_state": message.processing_state,
                    "content_excerpt": message.content_excerpt,
                }
                for message in messages
            ],
            "extraction_attempts": [
                {
                    "id": attempt.id,
                    "message_id": attempt.message_id,
                    "status": attempt.status,
                    "attempt_number": attempt.attempt_number,
                    "error_category": attempt.error_category,
                    "validation_summary": attempt.validation_summary,
                    "result_payload": attempt.result_payload,
                    "completed_at": attempt.completed_at,
                }
                for attempt in attempts
            ],
            "score_evaluations": [
                {
                    "id": evaluation.id,
                    "score": evaluation.score,
                    "priority": evaluation.priority,
                    "explanation": evaluation.explanation,
                    "evaluated_at": evaluation.evaluated_at,
                }
                for evaluation in evaluations
            ],
            "activities": [
                {
                    "id": activity.id,
                    "activity_type": activity.activity_type,
                    "status": activity.status,
                    "correlation_id": activity.correlation_id,
                    "safe_metadata": activity.safe_metadata,
                    "created_at": activity.created_at,
                }
                for activity in activities
            ],
            "reminders": [
                {
                    "id": reminder.id,
                    "reminder_type": reminder.reminder_type,
                    "due_at": reminder.due_at,
                    "status": reminder.status,
                    "correlation_id": reminder.correlation_id,
                    "triggered_at": reminder.triggered_at,
                    "suppressed_at": reminder.suppressed_at,
                }
                for reminder in reminders
            ],
        }

    def list_follow_ups(
        self,
        session: Session,
        *,
        now: datetime,
        due_only: bool = True,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        query = (
            select(Reminder, Lead, Contact, Conversation)
            .join(Lead, Lead.id == Reminder.lead_id)
            .join(Contact, Contact.id == Lead.contact_id)
            .join(Conversation, Conversation.id == Lead.conversation_id)
            .where(Reminder.status.in_(("pending", "due")))
            .order_by(Reminder.due_at.asc(), Reminder.id.asc())
            .limit(limit)
        )
        if due_only:
            query = query.where(Reminder.due_at <= now)
        return [
            {
                "id": reminder.id,
                "lead_id": lead.id,
                "subject": conversation.subject,
                "contact_name": contact.display_name or contact.company_name,
                "status": reminder.status,
                "reminder_type": reminder.reminder_type,
                "due_at": reminder.due_at,
                "priority": lead.priority,
                "owner_email": lead.owner_email,
            }
            for reminder, lead, contact, conversation in session.execute(query).all()
        ]

    @staticmethod
    def _lead_card(
        session: Session,
        lead: Lead,
        contact: Contact,
        conversation: Conversation,
    ) -> dict[str, Any]:
        latest_attempt = session.scalar(
            select(ExtractionAttempt)
            .where(ExtractionAttempt.lead_id == lead.id)
            .order_by(ExtractionAttempt.id.desc())
            .limit(1)
        )
        latest_message_state = session.scalar(
            select(Message.processing_state)
            .where(Message.lead_id == lead.id)
            .order_by(Message.received_at.desc(), Message.id.desc())
            .limit(1)
        )
        payload = latest_attempt.result_payload if latest_attempt else None
        payload = payload if isinstance(payload, dict) else {}
        review_state = None
        if latest_attempt is not None and latest_attempt.status in {"pending", "manual_review"}:
            review_state = latest_attempt.status
        elif latest_message_state in REVIEW_MESSAGE_STATES:
            review_state = latest_message_state
        elif lead.status == "Pending Extraction":
            review_state = "pending_extraction"
        return {
            "id": lead.id,
            "status": lead.status,
            "priority": lead.priority,
            "score": lead.score,
            "score_reason": lead.score_reason,
            "contact_name": contact.display_name or contact.company_name,
            "company_name": contact.company_name,
            "subject": conversation.subject,
            "service_interest": payload.get("service_interest"),
            "stated_budget": payload.get("stated_budget"),
            "business_summary": payload.get("business_summary"),
            "owner_email": lead.owner_email,
            "next_follow_up_at": lead.next_follow_up_at,
            "review_state": review_state,
        }
