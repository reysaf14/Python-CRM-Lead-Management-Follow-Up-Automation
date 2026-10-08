"""Sales-only follow-up scheduling and operator response suppression."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from sqlalchemy import desc, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.persistence.base import utc_now
from app.persistence.database import session_scope
from app.persistence.models import Activity, Lead, Message, Reminder, ScoreEvaluation


HIGH_FOLLOW_UP_DELAY = timedelta(hours=24)
HIGH_FOLLOW_UP_REMINDER_TYPE = "high_priority_follow_up"


@dataclass(frozen=True)
class FollowUpScanResult:
    """Sanitized outcome of one follow-up scan."""

    scanned_high_lead_count: int = 0
    not_due_count: int = 0
    reminder_created_count: int = 0
    reminder_existing_count: int = 0
    reminder_suppressed_count: int = 0
    error_category: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.error_category is None


@dataclass(frozen=True)
class SalesResponseOutcome:
    """Sanitized result of recording an operator response."""

    status: str
    suppressed_reminder_count: int = 0
    error_category: str | None = None


class FollowUpSchedulerService:
    """Create one sales reminder at the High-priority 24-hour deadline."""

    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        now_factory: Callable[[], datetime] = utc_now,
        follow_up_delay: timedelta = HIGH_FOLLOW_UP_DELAY,
        reminder_type: str = HIGH_FOLLOW_UP_REMINDER_TYPE,
    ) -> None:
        self._session_factory = session_factory
        self._now_factory = now_factory
        self._follow_up_delay = follow_up_delay
        self._reminder_type = reminder_type

    def scan_once(self) -> FollowUpScanResult:
        """Evaluate current High leads without sending any prospect message."""

        now = self._now_factory()
        try:
            with session_scope(self._session_factory) as session:
                leads = list(
                    session.scalars(select(Lead).where(Lead.priority == "High")).all()
                )
                not_due_count = 0
                reminder_created_count = 0
                reminder_existing_count = 0
                reminder_suppressed_count = 0

                for lead in leads:
                    evaluation = self._latest_high_evaluation(session, lead.id)
                    if evaluation is None:
                        continue
                    qualifying_at = self._qualifying_at(session, evaluation)
                    due_at = qualifying_at + self._follow_up_delay
                    lead.next_follow_up_at = due_at

                    reminder = session.scalar(
                        select(Reminder).where(
                            Reminder.lead_id == lead.id,
                            Reminder.reminder_type == self._reminder_type,
                            Reminder.due_at == due_at,
                        )
                    )
                    response_exists = self._response_exists(
                        session,
                        lead_id=lead.id,
                        qualifying_at=qualifying_at,
                    )
                    if response_exists:
                        if reminder is not None and reminder.status not in {
                            "suppressed",
                            "completed",
                        }:
                            reminder.status = "suppressed"
                            reminder.suppressed_at = now
                            reminder_suppressed_count += 1
                        lead.next_follow_up_at = None
                        continue

                    if now < due_at:
                        not_due_count += 1
                        if reminder is not None:
                            reminder_existing_count += 1
                        continue

                    if reminder is None:
                        reminder = Reminder(
                            lead_id=lead.id,
                            reminder_type=self._reminder_type,
                            due_at=due_at,
                            status="due",
                            correlation_id=self._correlation_id(lead.id, due_at),
                            triggered_at=now,
                        )
                        session.add(reminder)
                        session.flush()
                        session.add(
                            self._reminder_activity(
                                lead_id=lead.id,
                                correlation_id=reminder.correlation_id,
                            )
                        )
                        reminder_created_count += 1
                    elif reminder.status == "pending":
                        reminder.status = "due"
                        reminder.triggered_at = reminder.triggered_at or now
                        session.add(
                            self._reminder_activity(
                                lead_id=lead.id,
                                correlation_id=reminder.correlation_id,
                            )
                        )
                        reminder_existing_count += 1
                    else:
                        reminder_existing_count += 1

                return FollowUpScanResult(
                    scanned_high_lead_count=len(leads),
                    not_due_count=not_due_count,
                    reminder_created_count=reminder_created_count,
                    reminder_existing_count=reminder_existing_count,
                    reminder_suppressed_count=reminder_suppressed_count,
                )
        except SQLAlchemyError:
            return FollowUpScanResult(error_category="database_write_failed")

    def _latest_high_evaluation(
        self,
        session: Session,
        lead_id: int,
    ) -> ScoreEvaluation | None:
        return session.scalar(
            select(ScoreEvaluation)
            .where(
                ScoreEvaluation.lead_id == lead_id,
                ScoreEvaluation.priority == "High",
            )
            .order_by(desc(ScoreEvaluation.evaluated_at))
            .limit(1)
        )

    @staticmethod
    def _qualifying_at(session: Session, evaluation: ScoreEvaluation) -> datetime:
        if evaluation.source_message_id is not None:
            message = session.get(Message, evaluation.source_message_id)
            if message is not None:
                return FollowUpSchedulerService._as_utc(message.received_at)
        return FollowUpSchedulerService._as_utc(evaluation.evaluated_at)

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        """Treat timezone-less database values as UTC for deterministic scheduling."""

        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _response_exists(
        session: Session,
        *,
        lead_id: int,
        qualifying_at: datetime,
    ) -> bool:
        response_id = session.scalar(
            select(Activity.id)
            .where(
                Activity.lead_id == lead_id,
                Activity.activity_type == "sales_response",
                Activity.status == "completed",
                Activity.created_at >= qualifying_at,
            )
            .limit(1)
        )
        return response_id is not None

    @staticmethod
    def _correlation_id(lead_id: int, due_at: datetime) -> str:
        return f"follow-up:{lead_id}:{int(due_at.timestamp())}"

    @staticmethod
    def _reminder_activity(*, lead_id: int, correlation_id: str) -> Activity:
        return Activity(
            lead_id=lead_id,
            activity_type="follow_up_reminder",
            status="due",
            correlation_id=correlation_id,
            safe_metadata={"destination": "sales", "reminder_type": HIGH_FOLLOW_UP_REMINDER_TYPE},
        )


class SalesResponseService:
    """Record a sales response and suppress applicable reminders."""

    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        now_factory: Callable[[], datetime] = utc_now,
    ) -> None:
        self._session_factory = session_factory
        self._now_factory = now_factory

    def record_response(self, *, lead_id: int, correlation_id: str) -> SalesResponseOutcome:
        """Persist one operator response without reading or sending Gmail."""

        try:
            with session_scope(self._session_factory) as session:
                lead = session.get(Lead, lead_id)
                if lead is None:
                    return SalesResponseOutcome("failed", error_category="lead_not_found")

                existing = session.scalar(
                    select(Activity.id).where(
                        Activity.lead_id == lead_id,
                        Activity.activity_type == "sales_response",
                        Activity.correlation_id == correlation_id,
                    )
                )
                if existing is not None:
                    return SalesResponseOutcome("already_recorded")

                session.add(
                    Activity(
                        lead_id=lead_id,
                        activity_type="sales_response",
                        status="completed",
                        correlation_id=correlation_id,
                        safe_metadata={"channel": "operator"},
                    )
                )
                reminders = list(
                    session.scalars(
                        select(Reminder).where(
                            Reminder.lead_id == lead_id,
                            Reminder.status.in_(["pending", "due"]),
                        )
                    )
                )
                now = self._now_factory()
                for reminder in reminders:
                    reminder.status = "suppressed"
                    reminder.suppressed_at = now
                lead.next_follow_up_at = None
                return SalesResponseOutcome(
                    "recorded",
                    suppressed_reminder_count=len(reminders),
                )
        except SQLAlchemyError:
            return SalesResponseOutcome("failed", error_category="database_write_failed")
