"""Make player performance append-only and retain player-hero performance windows.

Revision ID: 0004_append_only_player_features
Revises: 0003_historical_provenance
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_append_only_player_features"
down_revision: str | Sequence[str] | None = "0003_historical_provenance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("uq_player_performance_map", "player_performance_maps", type_="unique")
    op.add_column(
        "player_performance_maps",
        sa.Column("source_historical_player_map_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        op.f("fk_player_performance_maps_source_historical_player_map_id_historical_player_maps"),
        "player_performance_maps",
        "historical_player_maps",
        ["source_historical_player_map_id"],
        ["id"],
    )
    op.create_index(
        "ix_player_performance_source",
        "player_performance_maps",
        ["source_historical_player_map_id"],
        unique=False,
    )
    op.create_unique_constraint(
        "uq_player_performance_version",
        "player_performance_maps",
        ["canonical_player_id", "canonical_map_id", "knowledge_cutoff", "model_version"],
    )
    op.add_column(
        "player_hero_snapshots",
        sa.Column("historical_performance", sa.Float(), nullable=True),
    )
    op.add_column(
        "player_hero_snapshots",
        sa.Column("recent_180d_performance", sa.Float(), nullable=True),
    )
    op.add_column(
        "player_hero_snapshots",
        sa.Column("current_patch_performance", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("player_hero_snapshots", "current_patch_performance")
    op.drop_column("player_hero_snapshots", "recent_180d_performance")
    op.drop_column("player_hero_snapshots", "historical_performance")
    op.drop_constraint("uq_player_performance_version", "player_performance_maps", type_="unique")
    op.drop_index("ix_player_performance_source", table_name="player_performance_maps")
    op.drop_constraint(
        op.f("fk_player_performance_maps_source_historical_player_map_id_historical_player_maps"),
        "player_performance_maps",
        type_="foreignkey",
    )
    op.drop_column("player_performance_maps", "source_historical_player_map_id")
    op.create_unique_constraint(
        "uq_player_performance_map",
        "player_performance_maps",
        ["canonical_player_id", "canonical_map_id"],
    )
