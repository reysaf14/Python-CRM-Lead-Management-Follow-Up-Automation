"""Add source-message identity for idempotent score evaluations."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0002_score_source_identity"
down_revision: Union[str, Sequence[str], None] = "0001_initial_crm_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "score_evaluations",
        sa.Column("source_message_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_score_evaluations_source_message_id",
        "score_evaluations",
        "messages",
        ["source_message_id"],
        ["id"],
    )
    op.create_unique_constraint(
        "uq_score_evaluations_source_identity",
        "score_evaluations",
        ["lead_id", "rule_version_id", "source_message_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_score_evaluations_source_identity",
        "score_evaluations",
        type_="unique",
    )
    op.drop_constraint(
        "fk_score_evaluations_source_message_id",
        "score_evaluations",
        type_="foreignkey",
    )
    op.drop_column("score_evaluations", "source_message_id")
