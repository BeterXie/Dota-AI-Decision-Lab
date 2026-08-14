"""Add canvas/charts enrichment columns to DLTV live observations.

Revision ID: 0020_dltv_live_canvas_charts
Revises: 0019_repair_non_map_market_identity
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020_dltv_live_canvas_charts"
down_revision: str | None = "0019_repair_non_map_market_identity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    connection = op.get_bind()
    if connection.dialect.name != "postgresql":
        return
    op.add_column("dltv_live_observations", sa.Column("canvas", sa.JSON(), nullable=True))
    op.add_column("dltv_live_observations", sa.Column("charts", sa.JSON(), nullable=True))


def downgrade() -> None:
    connection = op.get_bind()
    if connection.dialect.name != "postgresql":
        return
    op.drop_column("dltv_live_observations", "charts")
    op.drop_column("dltv_live_observations", "canvas")
