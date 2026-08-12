"""Persist append-only provider result evidence.

Revision ID: 0011_result_evidence
Revises: 0010_explicit_closing_odds
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_result_evidence"
down_revision: str | None = "0010_explicit_closing_odds"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "map_result_evidence",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("canonical_map_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("provider_match_id", sa.String(128), nullable=False),
        sa.Column("winner_team_id", sa.Uuid()),
        sa.Column("result_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("first_usable_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_event_id", sa.Uuid(), nullable=False),
        sa.Column("normalizer_version", sa.String(64), nullable=False),
        sa.Column("identity_confidence", sa.Float(), nullable=False),
        sa.Column("conflict_status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["canonical_map_id"], ["canonical_maps.id"]),
        sa.ForeignKeyConstraint(["winner_team_id"], ["canonical_teams.id"]),
        sa.UniqueConstraint("canonical_map_id", "raw_event_id", name="uq_result_evidence_raw"),
    )
    op.create_index(
        "ix_result_evidence_map_usable",
        "map_result_evidence",
        ["canonical_map_id", "first_usable_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_result_evidence_map_usable", table_name="map_result_evidence")
    op.drop_table("map_result_evidence")
