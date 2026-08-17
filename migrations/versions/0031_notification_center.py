"""Add user-scoped Notification Center bindings and deliveries.

Revision ID: 0031_notification_center
Revises: 0030_user_entitlements
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0031_notification_center"
down_revision: str | None = "0030_user_entitlements"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_DOCUMENT = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "notification_bindings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("channel", sa.String(16), nullable=False),
        sa.Column("destination_key", sa.String(512), nullable=False),
        sa.Column("destination", JSON_DOCUMENT, nullable=False),
        sa.Column("label", sa.String(255)),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user_accounts.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "channel",
            "destination_key",
            name="uq_notification_binding_destination",
        ),
    )
    op.create_index(
        "ix_notification_binding_user_status",
        "notification_bindings",
        ["user_id", "status", "channel"],
    )

    op.create_table(
        "notification_preferences",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("channel", sa.String(16), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user_accounts.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "user_id",
            "event_type",
            "channel",
            name="uq_notification_preference_user_event_channel",
        ),
    )
    op.create_index(
        "ix_notification_preference_lookup",
        "notification_preferences",
        ["user_id", "event_type", "channel"],
    )

    op.create_table(
        "notification_pairing_codes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("channel", sa.String(16), nullable=False),
        sa.Column("code_digest", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user_accounts.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("code_digest", name="uq_notification_pairing_code_digest"),
    )
    op.create_index(
        "ix_notification_pairing_user_channel",
        "notification_pairing_codes",
        ["user_id", "channel", "created_at"],
    )
    op.create_index(
        "ix_notification_pairing_expiry",
        "notification_pairing_codes",
        ["expires_at", "consumed_at"],
    )

    op.create_table(
        "notification_deliveries",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("binding_id", sa.Uuid(), nullable=False),
        sa.Column("channel", sa.String(16), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("decision_batch_key", sa.String(64), nullable=False),
        sa.Column("decision_ids", JSON_DOCUMENT, nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("provider_message_id", sa.String(255)),
        sa.Column("last_error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user_accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["binding_id"], ["notification_bindings.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["snapshot_id"], ["decision_snapshots.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "binding_id",
            "event_type",
            "snapshot_id",
            "decision_batch_key",
            name="uq_notification_delivery_binding_event_batch",
        ),
        sa.UniqueConstraint(
            "idempotency_key",
            name="uq_notification_delivery_idempotency",
        ),
    )
    op.create_index(
        "ix_notification_delivery_status_created",
        "notification_deliveries",
        ["status", "created_at"],
    )
    op.create_index(
        "ix_notification_delivery_user_created",
        "notification_deliveries",
        ["user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_notification_delivery_user_created", table_name="notification_deliveries")
    op.drop_index("ix_notification_delivery_status_created", table_name="notification_deliveries")
    op.drop_table("notification_deliveries")
    op.drop_index("ix_notification_pairing_expiry", table_name="notification_pairing_codes")
    op.drop_index("ix_notification_pairing_user_channel", table_name="notification_pairing_codes")
    op.drop_table("notification_pairing_codes")
    op.drop_index("ix_notification_preference_lookup", table_name="notification_preferences")
    op.drop_table("notification_preferences")
    op.drop_index("ix_notification_binding_user_status", table_name="notification_bindings")
    op.drop_table("notification_bindings")
