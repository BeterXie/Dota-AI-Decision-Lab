"""Add virtual shadow PnL settlement fields to decision evaluations.

Revision ID: 0024_virtual_pnl_evaluation
Revises: 0023_ai_virtual_bankroll
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0024_virtual_pnl_evaluation"
down_revision: str | None = "0023_ai_virtual_bankroll"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "decision_evaluations", sa.Column("virtual_pnl", sa.Numeric(14, 2), nullable=True)
    )
    op.add_column(
        "decision_evaluations", sa.Column("virtual_odds", sa.Numeric(12, 5), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("decision_evaluations", "virtual_odds")
    op.drop_column("decision_evaluations", "virtual_pnl")
