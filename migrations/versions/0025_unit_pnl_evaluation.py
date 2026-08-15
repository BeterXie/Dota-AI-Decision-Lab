"""Add standardized 1-unit PnL to decision evaluations.

Revision ID: 0025_unit_pnl_evaluation
Revises: 0024_virtual_pnl_evaluation
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0025_unit_pnl_evaluation"
down_revision: str | None = "0024_virtual_pnl_evaluation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "decision_evaluations", sa.Column("unit_pnl", sa.Numeric(14, 2), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("decision_evaluations", "unit_pnl")
