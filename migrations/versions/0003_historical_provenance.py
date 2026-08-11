"""Add historical team identity and normalization provenance.

Revision ID: 0003_historical_provenance
Revises: 0002_identity_mappings
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_historical_provenance"
down_revision: str | Sequence[str] | None = "0002_identity_mappings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("historical_maps", sa.Column("radiant_team_id", sa.Uuid(), nullable=True))
    op.add_column("historical_maps", sa.Column("dire_team_id", sa.Uuid(), nullable=True))
    op.add_column(
        "historical_maps", sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "historical_maps", sa.Column("normalizer_version", sa.String(length=64), nullable=True)
    )
    op.create_foreign_key(
        op.f("fk_historical_maps_radiant_team_id_canonical_teams"),
        "historical_maps",
        "canonical_teams",
        ["radiant_team_id"],
        ["id"],
    )
    op.create_foreign_key(
        op.f("fk_historical_maps_dire_team_id_canonical_teams"),
        "historical_maps",
        "canonical_teams",
        ["dire_team_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_historical_maps_dire_team_id_canonical_teams"),
        "historical_maps",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_historical_maps_radiant_team_id_canonical_teams"),
        "historical_maps",
        type_="foreignkey",
    )
    op.drop_column("historical_maps", "normalizer_version")
    op.drop_column("historical_maps", "fetched_at")
    op.drop_column("historical_maps", "dire_team_id")
    op.drop_column("historical_maps", "radiant_team_id")
