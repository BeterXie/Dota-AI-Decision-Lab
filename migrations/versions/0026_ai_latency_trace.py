"""Add end-to-end latency trace columns to AI decision records.

Revision ID: 0026_ai_latency_trace
Revises: 0025_unit_pnl_evaluation
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0026_ai_latency_trace"
down_revision: str | None = "0025_unit_pnl_evaluation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ai_decisions", sa.Column("job_enqueued_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "ai_decisions", sa.Column("job_claimed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "ai_decisions",
        sa.Column("input_prepare_started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "ai_decisions",
        sa.Column("input_prepare_completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "ai_decisions",
        sa.Column("decision_persisted_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ai_decisions", "decision_persisted_at")
    op.drop_column("ai_decisions", "input_prepare_completed_at")
    op.drop_column("ai_decisions", "input_prepare_started_at")
    op.drop_column("ai_decisions", "job_claimed_at")
    op.drop_column("ai_decisions", "job_enqueued_at")
