"""Record RayBet registry generation on odds observations.

Revision ID: 0007_market_metadata_version
Revises: 0006_live_effective_state
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_market_metadata_version"
down_revision: str | None = "0006_live_effective_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("odds_observations", sa.Column("metadata_version", sa.String(64)))


def downgrade() -> None:
    op.drop_column("odds_observations", "metadata_version")
