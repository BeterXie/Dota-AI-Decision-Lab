"""Replace SMTP message identity with Resend delivery identity.

Revision ID: 0014_resend_email_provider
Revises: 0013_decision_email_notifications
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_resend_email_provider"
down_revision: str | None = "0013_decision_email_notifications"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "uq_decision_email_message_id",
        "decision_email_notifications",
        type_="unique",
    )
    op.alter_column(
        "decision_email_notifications",
        "message_id",
        new_column_name="idempotency_key",
    )
    op.add_column(
        "decision_email_notifications",
        sa.Column("provider_message_id", sa.String(255)),
    )
    op.create_unique_constraint(
        "uq_decision_email_idempotency_key",
        "decision_email_notifications",
        ["idempotency_key"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_decision_email_idempotency_key",
        "decision_email_notifications",
        type_="unique",
    )
    op.drop_column("decision_email_notifications", "provider_message_id")
    op.alter_column(
        "decision_email_notifications",
        "idempotency_key",
        new_column_name="message_id",
    )
    op.create_unique_constraint(
        "uq_decision_email_message_id",
        "decision_email_notifications",
        ["message_id"],
    )
