"""Add canonical alias and provider identity mappings.

Revision ID: 0002_identity_mappings
Revises: 0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_identity_mappings"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "team_aliases",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("canonical_team_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("normalized_name", sa.String(length=255), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=True),
        sa.ForeignKeyConstraint(
            ["canonical_team_id"],
            ["canonical_teams.id"],
            name=op.f("fk_team_aliases_canonical_team_id_canonical_teams"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_team_aliases")),
        sa.UniqueConstraint(
            "canonical_team_id", "normalized_name", name="uq_team_alias_normalized"
        ),
    )
    op.create_index("ix_team_alias_lookup", "team_aliases", ["normalized_name"], unique=False)
    op.create_table(
        "provider_event_mappings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("provider_event_id", sa.String(length=128), nullable=False),
        sa.Column("canonical_event_id", sa.Uuid(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["canonical_event_id"],
            ["canonical_events.id"],
            name=op.f("fk_provider_event_mappings_canonical_event_id_canonical_events"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_provider_event_mappings")),
        sa.UniqueConstraint("provider", "provider_event_id", name="uq_provider_event_identity"),
    )
    op.create_table(
        "provider_hero_mappings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("provider_hero_id", sa.String(length=128), nullable=False),
        sa.Column("canonical_hero_id", sa.Integer(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["canonical_hero_id"],
            ["canonical_heroes.hero_id"],
            name=op.f("fk_provider_hero_mappings_canonical_hero_id_canonical_heroes"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_provider_hero_mappings")),
        sa.UniqueConstraint("provider", "provider_hero_id", name="uq_provider_hero_identity"),
    )


def downgrade() -> None:
    op.drop_table("provider_hero_mappings")
    op.drop_table("provider_event_mappings")
    op.drop_index("ix_team_alias_lookup", table_name="team_aliases")
    op.drop_table("team_aliases")
