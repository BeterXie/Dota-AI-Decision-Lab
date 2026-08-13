"""Clear map identity from non-map RayBet stages.

Revision ID: 0019_repair_non_map_market_identity
Revises: 0018_backfill_map_market_identity
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019_repair_non_map_market_identity"
down_revision: str | None = "0018_backfill_map_market_identity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    connection = op.get_bind()
    if connection.dialect.name != "postgresql":
        return
    connection.execute(
        sa.text(
            """
            UPDATE odds_observations
            SET canonical_map_id = NULL
            WHERE canonical_map_id IS NOT NULL
              AND canonical_series_id IS NOT NULL
              AND match_stage IS NOT NULL
              AND match_stage !~* '^\\s*(r[1-9][0-9]*|map\\s*r?[1-9][0-9]*)\\s*$'
            """
        )
    )


def downgrade() -> None:
    return None
