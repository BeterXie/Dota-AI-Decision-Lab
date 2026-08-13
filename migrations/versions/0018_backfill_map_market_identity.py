"""Backfill map identity for stage-specific odds after series merges.

Revision ID: 0018_backfill_map_market_identity
Revises: 0017_ti_team_alias_identity_merge
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018_backfill_map_market_identity"
down_revision: str | None = "0017_ti_team_alias_identity_merge"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    connection = op.get_bind()
    if connection.dialect.name != "postgresql":
        return

    # RayBet emits map-specific stages as r1/r2 (and occasionally "Map r1").
    # Only backfill when the series has exactly one canonical map for that
    # number. Match-level/final markets remain series-level because assigning
    # them to a map would invent identity evidence.
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
    connection.execute(
        sa.text(
            """
            UPDATE odds_observations AS odds
            SET canonical_map_id = map.id
            FROM canonical_maps AS map
            WHERE odds.canonical_map_id IS NULL
              AND odds.canonical_series_id = map.series_id
              AND odds.match_stage ~* '^\\s*(r[1-9][0-9]*|map\\s*r?[1-9][0-9]*)\\s*$'
              AND map.map_number = regexp_replace(
                    odds.match_stage, '[^0-9]', '', 'g'
                  )::integer
              AND NOT EXISTS (
                    SELECT 1
                    FROM canonical_maps AS duplicate
                    WHERE duplicate.series_id = map.series_id
                      AND duplicate.map_number = map.map_number
                      AND duplicate.id <> map.id
              )
            """
        )
    )


def downgrade() -> None:
    # The original series-level observations are still represented by their
    # canonical_series_id; clearing map identity would discard a verified
    # stage-to-map fact and is therefore intentionally not supported.
    return None
