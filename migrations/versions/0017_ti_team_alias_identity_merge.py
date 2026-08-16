"""Merge current TI team aliases and their split series identities.

Revision ID: 0017_ti_team_alias_identity_merge
Revises: 0016_ai_decision_after_ten_minutes
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017_ti_team_alias_identity_merge"
down_revision: str | None = "0016_ai_decision_after_ten_minutes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    connection = op.get_bind()
    if connection.dialect.name != "postgresql":
        return

    # The tournament audit found three provider-name splits. Provider IDs are
    # the evidence anchor; names alone are not used to merge canonical teams.
    for raybet_team_id, dltv_team_id in (
        ("16129", "7"),  # Liquid / Team Liquid
        ("16236", "3"),  # VG / Vici Gaming
        ("16259", "4837"),  # Spirit / Team Spirit
    ):
        _merge_provider_team_identity(
            connection,
            source_provider="raybet",
            source_provider_team_id=raybet_team_id,
            target_provider="dltv",
            target_provider_team_id=dltv_team_id,
        )

    # Preserve the RayBet series because its immutable PREMATCH snapshots and
    # odds observations already point there; move DLTV maps into that series.
    for raybet_match_id, dltv_series_id in (
        ("38423263", "427640"),  # Liquid vs Vici Gaming
        ("38423260", "427639"),  # Team Spirit vs Xtreme Gaming
    ):
        _merge_provider_series(
            connection,
            raybet_match_id=raybet_match_id,
            dltv_series_id=dltv_series_id,
        )


def downgrade() -> None:
    # Canonical identity merges intentionally preserve the unified identity.
    return None


def _mapping_team_id(connection, provider: str, provider_team_id: str):
    return connection.scalar(
        sa.text(
            """
            SELECT canonical_team_id
            FROM provider_team_mappings
            WHERE provider = :provider AND provider_team_id = :provider_team_id
            """
        ),
        {"provider": provider, "provider_team_id": provider_team_id},
    )


def _merge_provider_team_identity(
    connection,
    *,
    source_provider: str,
    source_provider_team_id: str,
    target_provider: str,
    target_provider_team_id: str,
) -> None:
    source_team_id = _mapping_team_id(connection, source_provider, source_provider_team_id)
    target_team_id = _mapping_team_id(connection, target_provider, target_provider_team_id)
    if source_team_id is None or target_team_id is None or source_team_id == target_team_id:
        return

    connection.execute(
        sa.text(
            """
            DELETE FROM team_aliases AS source
            USING team_aliases AS target
            WHERE source.canonical_team_id = :source
              AND target.canonical_team_id = :target
              AND source.normalized_name = target.normalized_name
            """
        ),
        {"source": source_team_id, "target": target_team_id},
    )
    connection.execute(
        sa.text(
            "UPDATE provider_team_mappings SET canonical_team_id = :target "
            "WHERE canonical_team_id = :source"
        ),
        {"source": source_team_id, "target": target_team_id},
    )
    connection.execute(
        sa.text(
            "UPDATE team_aliases SET canonical_team_id = :target WHERE canonical_team_id = :source"
        ),
        {"source": source_team_id, "target": target_team_id},
    )
    references = {
        "canonical_series": ("team_a_id", "team_b_id"),
        "odds_observations": ("selection_team_id",),
        "historical_maps": ("radiant_team_id", "dire_team_id", "winner_team_id"),
        "historical_player_maps": ("canonical_team_id", "opponent_team_id"),
        "team_rating_snapshots": ("canonical_team_id",),
        "team_form_snapshots": ("canonical_team_id",),
        "map_results": ("winner_team_id",),
        "map_result_evidence": ("winner_team_id",),
    }
    for table, columns in references.items():
        for column in columns:
            connection.execute(
                sa.text(  # noqa: S608 - table/column come only from closed migration constants
                    f"UPDATE {table} SET {column} = :target WHERE {column} = :source"  # noqa: S608 - closed migration identifiers
                ),
                {"source": source_team_id, "target": target_team_id},
            )
    connection.execute(
        sa.text("DELETE FROM canonical_teams WHERE id = :source"),
        {"source": source_team_id},
    )


def _merge_provider_series(connection, *, raybet_match_id: str, dltv_series_id: str) -> None:
    target_series_id = connection.scalar(
        sa.text(
            """
            SELECT canonical_series_id FROM provider_match_mappings
            WHERE provider = 'raybet' AND provider_match_id = :provider_match_id
            """
        ),
        {"provider_match_id": raybet_match_id},
    )
    source_series_id = connection.scalar(
        sa.text(
            """
            SELECT canonical_series_id FROM provider_match_mappings
            WHERE provider = 'dltv' AND provider_match_id = :provider_match_id
            """
        ),
        {"provider_match_id": dltv_series_id},
    )
    if source_series_id is None or target_series_id is None or source_series_id == target_series_id:
        return

    connection.execute(
        sa.text("UPDATE canonical_maps SET series_id = :target WHERE series_id = :source"),
        {"source": source_series_id, "target": target_series_id},
    )
    connection.execute(
        sa.text(
            "UPDATE provider_match_mappings SET canonical_series_id = :target "
            "WHERE canonical_series_id = :source"
        ),
        {"source": source_series_id, "target": target_series_id},
    )
    connection.execute(
        sa.text(
            "UPDATE odds_observations SET canonical_series_id = :target "
            "WHERE canonical_series_id = :source"
        ),
        {"source": source_series_id, "target": target_series_id},
    )
    connection.execute(
        sa.text("DELETE FROM canonical_series WHERE id = :source"),
        {"source": source_series_id},
    )
