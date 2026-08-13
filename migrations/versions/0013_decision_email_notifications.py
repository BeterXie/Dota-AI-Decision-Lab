"""Persist durable decision email notifications.

Revision ID: 0013_decision_email_notifications
Revises: 0012_nullable_draft_heroes
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013_decision_email_notifications"
down_revision: str | None = "0012_nullable_draft_heroes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "decision_email_notifications",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("snapshot_hash", sa.String(128), nullable=False),
        sa.Column("decision_batch_key", sa.String(255), nullable=False),
        sa.Column("sender", sa.String(320), nullable=False),
        sa.Column(
            "recipients",
            sa.JSON().with_variant(
                postgresql.JSONB(astext_type=sa.Text()),
                "postgresql",
            ),
            nullable=False,
        ),
        sa.Column("subject", sa.String(512), nullable=False),
        sa.Column("text_body", sa.Text(), nullable=False),
        sa.Column("html_body", sa.Text(), nullable=False),
        sa.Column("template_version", sa.String(64), nullable=False),
        sa.Column("message_id", sa.String(255), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["snapshot_id"], ["decision_snapshots.id"]),
        sa.UniqueConstraint(
            "snapshot_id",
            "decision_batch_key",
            name="uq_decision_email_snapshot_batch",
        ),
        sa.UniqueConstraint("message_id", name="uq_decision_email_message_id"),
    )
    op.create_index(
        "ix_decision_email_status_created",
        "decision_email_notifications",
        ["status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_decision_email_status_created",
        table_name="decision_email_notifications",
    )
    op.drop_table("decision_email_notifications")
