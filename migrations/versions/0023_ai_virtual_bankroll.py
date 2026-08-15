"""Add virtual shadow bankroll and stake to AI decisions.

Revision ID: 0023_ai_virtual_bankroll
Revises: 0022_ai_view_experiment_identity
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023_ai_virtual_bankroll"
down_revision: str | None = "0022_ai_view_experiment_identity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("ai_decisions", sa.Column("bankroll_before", sa.Numeric(14, 2), nullable=True))
    op.add_column("ai_decisions", sa.Column("stake", sa.Numeric(14, 2), nullable=True))


def downgrade() -> None:
    op.drop_column("ai_decisions", "stake")
    op.drop_column("ai_decisions", "bankroll_before")
