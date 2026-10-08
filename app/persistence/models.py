"""M1 PostgreSQL CRM persistence models.

The schema stores normalized operational state and approved metadata. Raw email
content is not written to application logs; later intake code must enforce the
approved excerpt/minimization policy before populating content fields.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.persistence.base import Base, TimestampMixin


class MailboxSyncState(TimestampMixin, Base):
    __tablename__ = "mailbox_sync_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mailbox_key: Mapped[str] = mapped_column(String(320), nullable=False)
    label_name: Mapped[str] = mapped_column(String(255), nullable=False)
    last_successful_cursor: Mapped[str | None] = mapped_column(String(255))
    last_successful_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    state: Mapped[str] = mapped_column(
        String(32), nullable=False, default="ready", server_default="ready"
    )
    error_category: Mapped[str | None] = mapped_column(String(80))

    __table_args__ = (
        UniqueConstraint("mailbox_key", name="uq_mailbox_sync_state_mailbox_key"),
    )


class Contact(TimestampMixin, Base):
    __tablename__ = "contacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email_normalized: Mapped[str] = mapped_column(String(320), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255))
    company_name: Mapped[str | None] = mapped_column(String(255))

    conversations: Mapped[list["Conversation"]] = relationship(back_populates="contact")
    leads: Mapped[list["Lead"]] = relationship(back_populates="contact")

    __table_args__ = (UniqueConstraint("email_normalized", name="uq_contacts_email_normalized"),)


class Conversation(TimestampMixin, Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider_thread_id: Mapped[str] = mapped_column(String(255), nullable=False)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id"), nullable=False)
    subject: Mapped[str | None] = mapped_column(String(998))
    state: Mapped[str] = mapped_column(
        String(32), nullable=False, default="active", server_default="active"
    )

    contact: Mapped[Contact] = relationship(back_populates="conversations")
    messages: Mapped[list["Message"]] = relationship(back_populates="conversation")
    leads: Mapped[list["Lead"]] = relationship(back_populates="conversation")
    activities: Mapped[list["Activity"]] = relationship(back_populates="conversation")

    __table_args__ = (
        UniqueConstraint("provider_thread_id", name="uq_conversations_provider_thread_id"),
    )


class Lead(TimestampMixin, Base):
    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id"), nullable=False)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"), nullable=False)
    status: Mapped[str] = mapped_column(
        String(40), nullable=False, default="New", server_default="New"
    )
    priority: Mapped[str | None] = mapped_column(String(20))
    score: Mapped[int | None] = mapped_column(Integer)
    score_reason: Mapped[str | None] = mapped_column(Text)
    owner_email: Mapped[str | None] = mapped_column(String(320))
    next_follow_up_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    contact: Mapped[Contact] = relationship(back_populates="leads")
    conversation: Mapped[Conversation] = relationship(back_populates="leads")
    messages: Mapped[list["Message"]] = relationship(back_populates="lead")
    extraction_attempts: Mapped[list["ExtractionAttempt"]] = relationship(
        back_populates="lead"
    )
    score_evaluations: Mapped[list["ScoreEvaluation"]] = relationship(back_populates="lead")
    activities: Mapped[list["Activity"]] = relationship(back_populates="lead")
    reminders: Mapped[list["Reminder"]] = relationship(back_populates="lead")

    __table_args__ = (
        UniqueConstraint("conversation_id", name="uq_leads_conversation_id"),
        Index("ix_leads_status_priority", "status", "priority"),
    )


class Message(TimestampMixin, Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider_message_id: Mapped[str] = mapped_column(String(255), nullable=False)
    provider_thread_id: Mapped[str] = mapped_column(String(255), nullable=False)
    conversation_id: Mapped[int | None] = mapped_column(ForeignKey("conversations.id"))
    lead_id: Mapped[int | None] = mapped_column(ForeignKey("leads.id"))
    sender_email: Mapped[str] = mapped_column(String(320), nullable=False)
    sender_name: Mapped[str | None] = mapped_column(String(255))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    subject: Mapped[str | None] = mapped_column(String(998))
    content_excerpt: Mapped[str | None] = mapped_column(Text)
    processing_state: Mapped[str] = mapped_column(
        String(40), nullable=False, default="received", server_default="received"
    )
    is_auto_reply: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    is_relevant: Mapped[bool | None] = mapped_column(Boolean)

    conversation: Mapped[Conversation | None] = relationship(back_populates="messages")
    lead: Mapped[Lead | None] = relationship(back_populates="messages")
    extraction_attempts: Mapped[list["ExtractionAttempt"]] = relationship(
        back_populates="message"
    )

    __table_args__ = (
        UniqueConstraint("provider_message_id", name="uq_messages_provider_message_id"),
        Index("ix_messages_provider_thread_id", "provider_thread_id"),
        Index("ix_messages_processing_state", "processing_state"),
    )


class ExtractionAttempt(TimestampMixin, Base):
    __tablename__ = "extraction_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id"), nullable=False)
    lead_id: Mapped[int | None] = mapped_column(ForeignKey("leads.id"))
    extraction_policy_version: Mapped[str] = mapped_column(String(80), nullable=False)
    attempt_number: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending", server_default="pending"
    )
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retryable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    error_category: Mapped[str | None] = mapped_column(String(80))
    validation_summary: Mapped[str | None] = mapped_column(Text)
    result_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    message: Mapped[Message] = relationship(back_populates="extraction_attempts")
    lead: Mapped[Lead | None] = relationship(back_populates="extraction_attempts")

    __table_args__ = (
        UniqueConstraint(
            "message_id",
            "extraction_policy_version",
            "attempt_number",
            name="uq_extraction_attempt_identity",
        ),
        Index("ix_extraction_attempts_status", "status"),
    )


class ScoringRuleVersion(TimestampMixin, Base):
    __tablename__ = "scoring_rule_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    rules_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    evaluations: Mapped[list["ScoreEvaluation"]] = relationship(back_populates="rule_version")

    __table_args__ = (UniqueConstraint("version", name="uq_scoring_rule_versions_version"),)


class ScoreEvaluation(TimestampMixin, Base):
    __tablename__ = "score_evaluations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id"), nullable=False)
    rule_version_id: Mapped[int] = mapped_column(
        ForeignKey("scoring_rule_versions.id"), nullable=False
    )
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    priority: Mapped[str] = mapped_column(String(20), nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    input_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    lead: Mapped[Lead] = relationship(back_populates="score_evaluations")
    rule_version: Mapped[ScoringRuleVersion] = relationship(back_populates="evaluations")

    __table_args__ = (Index("ix_score_evaluations_lead_evaluated_at", "lead_id", "evaluated_at"),)


class Activity(TimestampMixin, Base):
    __tablename__ = "activities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lead_id: Mapped[int | None] = mapped_column(ForeignKey("leads.id"))
    conversation_id: Mapped[int | None] = mapped_column(ForeignKey("conversations.id"))
    activity_type: Mapped[str] = mapped_column(String(60), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(120), nullable=False)
    safe_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    lead: Mapped[Lead | None] = relationship(back_populates="activities")
    conversation: Mapped[Conversation | None] = relationship(back_populates="activities")

    __table_args__ = (Index("ix_activities_correlation_id", "correlation_id"),)


class Reminder(TimestampMixin, Base):
    __tablename__ = "reminders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id"), nullable=False)
    reminder_type: Mapped[str] = mapped_column(String(60), nullable=False)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending", server_default="pending"
    )
    correlation_id: Mapped[str] = mapped_column(String(120), nullable=False)
    triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    suppressed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    lead: Mapped[Lead] = relationship(back_populates="reminders")

    __table_args__ = (
        UniqueConstraint("lead_id", "reminder_type", "due_at", name="uq_reminder_due_identity"),
        Index("ix_reminders_status_due_at", "status", "due_at"),
    )
