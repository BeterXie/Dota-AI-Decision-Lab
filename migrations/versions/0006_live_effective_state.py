"""Persist DLTV connection and effective-state timing metadata.

Revision ID: 0006_live_effective_state
Revises: 0005_draft_curve_idempotency
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_live_effective_state"
down_revision: str | None = "0005_draft_curve_idempotency"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("provider_raw_events", sa.Column("connection_id", sa.String(64)))
    op.add_column("provider_raw_events", sa.Column("reconnect_generation", sa.Integer()))
    op.add_column("provider_raw_events", sa.Column("normalized_state_hash", sa.String(128)))
    op.add_column("provider_raw_events", sa.Column("is_duplicate", sa.Boolean()))

    op.add_column("dltv_live_observations", sa.Column("connection_id", sa.String(64)))
    op.add_column(
        "dltv_live_observations",
        sa.Column("reconnect_generation", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "dltv_live_observations",
        sa.Column("last_message_received_at", sa.DateTime(timezone=True)),
    )
    op.add_column(
        "dltv_live_observations",
        sa.Column("last_state_change_received_at", sa.DateTime(timezone=True)),
    )
    op.execute(
        """
        UPDATE dltv_live_observations
        SET last_message_received_at = received_at,
            last_state_change_received_at = received_at
        """
    )
    op.alter_column("dltv_live_observations", "last_message_received_at", nullable=False)
    op.alter_column("dltv_live_observations", "last_state_change_received_at", nullable=False)
    op.alter_column("dltv_live_observations", "reconnect_generation", server_default=None)


def downgrade() -> None:
    op.drop_column("dltv_live_observations", "last_state_change_received_at")
    op.drop_column("dltv_live_observations", "last_message_received_at")
    op.drop_column("dltv_live_observations", "reconnect_generation")
    op.drop_column("dltv_live_observations", "connection_id")
    op.drop_column("provider_raw_events", "is_duplicate")
    op.drop_column("provider_raw_events", "normalized_state_hash")
    op.drop_column("provider_raw_events", "reconnect_generation")
    op.drop_column("provider_raw_events", "connection_id")
