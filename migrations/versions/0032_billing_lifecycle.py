"""Add provider-neutral billing lifecycle records.

Revision ID: 0032_billing_lifecycle
Revises: 0031_notification_center
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0032_billing_lifecycle"
down_revision: str | None = "0031_notification_center"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "billing_subscriptions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("subscription_ref", sa.String(160), nullable=False),
        sa.Column("customer_ref", sa.String(160)),
        sa.Column("plan_key", sa.String(64), nullable=False),
        sa.Column("access_state", sa.String(16), nullable=False),
        sa.Column("provider_status", sa.String(64)),
        sa.Column("current_period_end", sa.DateTime(timezone=True)),
        sa.Column("last_event_occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user_accounts.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "provider",
            "subscription_ref",
            name="uq_billing_subscriptions_provider_ref",
        ),
    )
    op.create_index(
        "ix_billing_subscriptions_user_status",
        "billing_subscriptions",
        ["user_id", "access_state"],
    )

    op.create_table(
        "billing_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("event_ref", sa.String(160), nullable=False),
        sa.Column("subscription_ref", sa.String(160), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload_digest", sa.String(64), nullable=False),
        sa.Column("applied", sa.Boolean(), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user_accounts.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("provider", "event_ref", name="uq_billing_events_provider_ref"),
    )
    op.create_index(
        "ix_billing_events_subscription",
        "billing_events",
        ["provider", "subscription_ref"],
    )


def downgrade() -> None:
    op.drop_index("ix_billing_events_subscription", table_name="billing_events")
    op.drop_table("billing_events")
    op.drop_index("ix_billing_subscriptions_user_status", table_name="billing_subscriptions")
    op.drop_table("billing_subscriptions")
