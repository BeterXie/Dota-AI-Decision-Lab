"""Replace negative-horizon closing with an explicit capture type.

Revision ID: 0010_explicit_closing_odds
Revises: 0009_ai_experiment_identity
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010_explicit_closing_odds"
down_revision: str | None = "0009_ai_experiment_identity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("decision_future_odds", sa.Column("capture_type", sa.String(32)))
    op.add_column("decision_future_odds", sa.Column("triggered_at", sa.DateTime(timezone=True)))
    op.add_column("decision_future_odds", sa.Column("market_type", sa.String(128)))
    op.add_column("decision_future_odds", sa.Column("match_stage", sa.String(64)))
    op.add_column("decision_future_odds", sa.Column("market_status", sa.String(32)))
    op.add_column("decision_future_odds", sa.Column("capture_policy_version", sa.String(64)))
    op.add_column(
        "decision_future_odds",
        sa.Column(
            "pair_quality",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
        ),
    )
    op.add_column("decision_future_odds", sa.Column("pair_skew_seconds", sa.Float()))
    op.execute(
        """
        UPDATE decision_future_odds
        SET capture_type = CASE WHEN horizon_seconds = -1 THEN 'CLOSING' ELSE 'TIME_HORIZON' END,
            triggered_at = due_at,
            capture_policy_version = CASE
                WHEN horizon_seconds = -1 THEN 'closing-policy-v1'
                ELSE 'time-horizon-v1'
            END,
            pair_quality = '{}',
            horizon_seconds = CASE WHEN horizon_seconds = -1 THEN NULL ELSE horizon_seconds END
        """
    )
    op.alter_column("decision_future_odds", "capture_type", nullable=False)
    op.alter_column("decision_future_odds", "triggered_at", nullable=False)
    op.alter_column("decision_future_odds", "capture_policy_version", nullable=False)
    op.alter_column("decision_future_odds", "pair_quality", nullable=False)
    op.alter_column("decision_future_odds", "horizon_seconds", nullable=True)
    op.drop_constraint("uq_future_odds_horizon", "decision_future_odds", type_="unique")
    op.create_unique_constraint(
        "uq_future_odds_capture",
        "decision_future_odds",
        ["decision_snapshot_id", "capture_type", "due_at"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_future_odds_capture", "decision_future_odds", type_="unique")
    op.execute(
        "UPDATE decision_future_odds SET horizon_seconds = -1 WHERE capture_type = 'CLOSING'"
    )
    op.alter_column("decision_future_odds", "horizon_seconds", nullable=False)
    op.create_unique_constraint(
        "uq_future_odds_horizon",
        "decision_future_odds",
        ["decision_snapshot_id", "horizon_seconds", "due_at"],
    )
    op.drop_column("decision_future_odds", "capture_policy_version")
    op.drop_column("decision_future_odds", "pair_skew_seconds")
    op.drop_column("decision_future_odds", "pair_quality")
    op.drop_column("decision_future_odds", "market_status")
    op.drop_column("decision_future_odds", "match_stage")
    op.drop_column("decision_future_odds", "market_type")
    op.drop_column("decision_future_odds", "triggered_at")
    op.drop_column("decision_future_odds", "capture_type")
