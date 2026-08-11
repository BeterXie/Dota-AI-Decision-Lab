"""Enforce one R.O.S.H. curve per immutable draft and model version.

Revision ID: 0005_draft_curve_idempotency
Revises: 0004_append_only_player_features
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005_draft_curve_idempotency"
down_revision: str | Sequence[str] | None = "0004_append_only_player_features"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_draft_curve_snapshot_model",
        "draft_minute_curves",
        ["draft_snapshot_id", "model_version"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_draft_curve_snapshot_model", "draft_minute_curves", type_="unique")
