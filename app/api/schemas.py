"""Pydantic contracts for private operator API responses and actions."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SummaryResponse(BaseModel):
    new_leads: int
    high_priority_leads: int
    follow_ups_due: int
    pending_extraction_or_manual_review: int


class LeadCardResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    priority: str | None = None
    score: int | None = None
    score_reason: str | None = None
    contact_name: str | None = None
    company_name: str | None = None
    subject: str | None = None
    service_interest: str | None = None
    stated_budget: str | None = None
    business_summary: str | None = None
    owner_email: str | None = None
    next_follow_up_at: datetime | None = None
    review_state: str | None = None


class MessageResponse(BaseModel):
    id: int
    subject: str | None = None
    sender_email: str
    received_at: datetime
    processing_state: str
    content_excerpt: str | None = None


class ExtractionAttemptResponse(BaseModel):
    id: int
    message_id: int
    status: str
    attempt_number: int
    error_category: str | None = None
    validation_summary: str | None = None
    result_payload: dict[str, Any] | None = None
    completed_at: datetime | None = None


class ScoreEvaluationResponse(BaseModel):
    id: int
    score: int
    priority: str
    explanation: str
    evaluated_at: datetime


class ActivityResponse(BaseModel):
    id: int
    activity_type: str
    status: str
    correlation_id: str
    safe_metadata: dict[str, Any] | None = None
    created_at: datetime


class ReminderResponse(BaseModel):
    id: int
    reminder_type: str
    due_at: datetime
    status: str
    correlation_id: str
    triggered_at: datetime | None = None
    suppressed_at: datetime | None = None


class LeadDetailResponse(LeadCardResponse):
    contact_email: str
    conversation_state: str
    messages: list[MessageResponse]
    extraction_attempts: list[ExtractionAttemptResponse]
    score_evaluations: list[ScoreEvaluationResponse]
    activities: list[ActivityResponse]
    reminders: list[ReminderResponse]


class FollowUpResponse(BaseModel):
    id: int
    lead_id: int
    subject: str | None = None
    contact_name: str | None = None
    status: str
    reminder_type: str
    due_at: datetime
    priority: str | None = None
    owner_email: str | None = None


class RecordResponseRequest(BaseModel):
    correlation_id: str = Field(min_length=1, max_length=120)


class RecordResponseResult(BaseModel):
    status: str
    suppressed_reminder_count: int = 0
