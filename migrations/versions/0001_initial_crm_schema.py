"""Create the M1 internal CRM persistence schema."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0001_initial_crm_schema"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def upgrade() -> None:
    op.create_table(
        "mailbox_sync_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("mailbox_key", sa.String(length=320), nullable=False),
        sa.Column("label_name", sa.String(length=255), nullable=False),
        sa.Column("last_successful_cursor", sa.String(length=255)),
        sa.Column("last_successful_sync_at", sa.DateTime(timezone=True)),
        sa.Column("state", sa.String(length=32), nullable=False, server_default="ready"),
        sa.Column("error_category", sa.String(length=80)),
        *_timestamps(),
        sa.UniqueConstraint("mailbox_key", name="uq_mailbox_sync_state_mailbox_key"),
    )

    op.create_table(
        "contacts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email_normalized", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=255)),
        sa.Column("company_name", sa.String(length=255)),
        *_timestamps(),
        sa.UniqueConstraint("email_normalized", name="uq_contacts_email_normalized"),
    )

    op.create_table(
        "conversations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider_thread_id", sa.String(length=255), nullable=False),
        sa.Column("contact_id", sa.Integer(), sa.ForeignKey("contacts.id"), nullable=False),
        sa.Column("subject", sa.String(length=998)),
        sa.Column("state", sa.String(length=32), nullable=False, server_default="active"),
        *_timestamps(),
        sa.UniqueConstraint("provider_thread_id", name="uq_conversations_provider_thread_id"),
    )

    op.create_table(
        "leads",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("contact_id", sa.Integer(), sa.ForeignKey("contacts.id"), nullable=False),
        sa.Column("conversation_id", sa.Integer(), sa.ForeignKey("conversations.id"), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="New"),
        sa.Column("priority", sa.String(length=20)),
        sa.Column("score", sa.Integer()),
        sa.Column("score_reason", sa.Text()),
        sa.Column("owner_email", sa.String(length=320)),
        sa.Column("next_follow_up_at", sa.DateTime(timezone=True)),
        *_timestamps(),
        sa.UniqueConstraint("conversation_id", name="uq_leads_conversation_id"),
    )
    op.create_index("ix_leads_status_priority", "leads", ["status", "priority"])

    op.create_table(
        "messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider_message_id", sa.String(length=255), nullable=False),
        sa.Column("provider_thread_id", sa.String(length=255), nullable=False),
        sa.Column("conversation_id", sa.Integer(), sa.ForeignKey("conversations.id")),
        sa.Column("lead_id", sa.Integer(), sa.ForeignKey("leads.id")),
        sa.Column("sender_email", sa.String(length=320), nullable=False),
        sa.Column("sender_name", sa.String(length=255)),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("subject", sa.String(length=998)),
        sa.Column("content_excerpt", sa.Text()),
        sa.Column("processing_state", sa.String(length=40), nullable=False, server_default="received"),
        sa.Column("is_auto_reply", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_relevant", sa.Boolean()),
        *_timestamps(),
        sa.UniqueConstraint("provider_message_id", name="uq_messages_provider_message_id"),
    )
    op.create_index("ix_messages_provider_thread_id", "messages", ["provider_thread_id"])
    op.create_index("ix_messages_processing_state", "messages", ["processing_state"])

    op.create_table(
        "extraction_attempts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("message_id", sa.Integer(), sa.ForeignKey("messages.id"), nullable=False),
        sa.Column("lead_id", sa.Integer(), sa.ForeignKey("leads.id")),
        sa.Column("extraction_policy_version", sa.String(length=80), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("retryable", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("error_category", sa.String(length=80)),
        sa.Column("validation_summary", sa.Text()),
        sa.Column("result_payload", sa.JSON()),
        *_timestamps(),
        sa.UniqueConstraint(
            "message_id",
            "extraction_policy_version",
            "attempt_number",
            name="uq_extraction_attempt_identity",
        ),
    )
    op.create_index("ix_extraction_attempts_status", "extraction_attempts", ["status"])

    op.create_table(
        "scoring_rule_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("version", sa.String(length=80), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("rules_payload", sa.JSON(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.false()),
        *_timestamps(),
        sa.UniqueConstraint("version", name="uq_scoring_rule_versions_version"),
    )

    op.create_table(
        "score_evaluations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("lead_id", sa.Integer(), sa.ForeignKey("leads.id"), nullable=False),
        sa.Column("rule_version_id", sa.Integer(), sa.ForeignKey("scoring_rule_versions.id"), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("priority", sa.String(length=20), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("input_snapshot", sa.JSON(), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        *_timestamps(),
    )
    op.create_index(
        "ix_score_evaluations_lead_evaluated_at",
        "score_evaluations",
        ["lead_id", "evaluated_at"],
    )

    op.create_table(
        "activities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("lead_id", sa.Integer(), sa.ForeignKey("leads.id")),
        sa.Column("conversation_id", sa.Integer(), sa.ForeignKey("conversations.id")),
        sa.Column("activity_type", sa.String(length=60), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("correlation_id", sa.String(length=120), nullable=False),
        sa.Column("safe_metadata", sa.JSON()),
        *_timestamps(),
    )
    op.create_index("ix_activities_correlation_id", "activities", ["correlation_id"])

    op.create_table(
        "reminders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("lead_id", sa.Integer(), sa.ForeignKey("leads.id"), nullable=False),
        sa.Column("reminder_type", sa.String(length=60), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("correlation_id", sa.String(length=120), nullable=False),
        sa.Column("triggered_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("suppressed_at", sa.DateTime(timezone=True)),
        *_timestamps(),
        sa.UniqueConstraint("lead_id", "reminder_type", "due_at", name="uq_reminder_due_identity"),
    )
    op.create_index("ix_reminders_status_due_at", "reminders", ["status", "due_at"])


def downgrade() -> None:
    op.drop_index("ix_reminders_status_due_at", table_name="reminders")
    op.drop_table("reminders")
    op.drop_index("ix_activities_correlation_id", table_name="activities")
    op.drop_table("activities")
    op.drop_index("ix_score_evaluations_lead_evaluated_at", table_name="score_evaluations")
    op.drop_table("score_evaluations")
    op.drop_table("scoring_rule_versions")
    op.drop_index("ix_extraction_attempts_status", table_name="extraction_attempts")
    op.drop_table("extraction_attempts")
    op.drop_index("ix_messages_processing_state", table_name="messages")
    op.drop_index("ix_messages_provider_thread_id", table_name="messages")
    op.drop_table("messages")
    op.drop_index("ix_leads_status_priority", table_name="leads")
    op.drop_table("leads")
    op.drop_table("conversations")
    op.drop_table("contacts")
    op.drop_table("mailbox_sync_state")
