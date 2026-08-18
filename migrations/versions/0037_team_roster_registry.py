"""Add maintained team, player and staff roster registry.

Revision ID: 0037_team_roster_registry
Revises: 0036_external_auth_identities
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0037_team_roster_registry"
down_revision: str | None = "0036_external_auth_identities"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "team_profiles",
        sa.Column("canonical_team_id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=160), nullable=True),
        sa.Column("short_name", sa.String(length=64), nullable=True),
        sa.Column("valve_team_id", sa.BigInteger(), nullable=True),
        sa.Column("country_code", sa.String(length=2), nullable=True),
        sa.Column("logo_url", sa.Text(), nullable=True),
        sa.Column("logo_source", sa.String(length=64), nullable=True),
        sa.Column("website_url", sa.Text(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["canonical_team_id"], ["canonical_teams.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("canonical_team_id"),
        sa.UniqueConstraint("slug", name="uq_team_profiles_slug"),
        sa.UniqueConstraint("valve_team_id", name="uq_team_profiles_valve_team_id"),
    )

    op.create_table(
        "player_profiles",
        sa.Column("canonical_player_id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=160), nullable=True),
        sa.Column("real_name", sa.String(length=255), nullable=True),
        sa.Column("country_code", sa.String(length=2), nullable=True),
        sa.Column("avatar_url", sa.Text(), nullable=True),
        sa.Column("avatar_source", sa.String(length=64), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["canonical_player_id"], ["canonical_players.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("canonical_player_id"),
        sa.UniqueConstraint("slug", name="uq_player_profiles_slug"),
    )

    op.create_table(
        "canonical_staff",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("real_name", sa.String(length=255), nullable=True),
        sa.Column("country_code", sa.String(length=2), nullable=True),
        sa.Column("avatar_url", sa.Text(), nullable=True),
        sa.Column("avatar_source", sa.String(length=64), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "team_roster_memberships",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("team_id", sa.Uuid(), nullable=False),
        sa.Column("player_id", sa.Uuid(), nullable=True),
        sa.Column("staff_id", sa.Uuid(), nullable=True),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("position", sa.Integer(), nullable=True),
        sa.Column("is_standin", sa.Boolean(), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_name", sa.String(length=64), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(player_id IS NOT NULL AND staff_id IS NULL) OR "
            "(player_id IS NULL AND staff_id IS NOT NULL)",
            name="roster_member_exactly_one_subject",
        ),
        sa.CheckConstraint(
            "position IS NULL OR (position >= 1 AND position <= 5)",
            name="roster_position_range",
        ),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from",
            name="roster_valid_range",
        ),
        sa.ForeignKeyConstraint(["player_id"], ["canonical_players.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["staff_id"], ["canonical_staff.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["team_id"], ["canonical_teams.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_team_roster_team_active",
        "team_roster_memberships",
        ["team_id", "valid_to"],
        unique=False,
    )
    op.create_index(
        "ix_team_roster_player_timeline",
        "team_roster_memberships",
        ["player_id", "valid_from", "valid_to"],
        unique=False,
    )
    op.create_index(
        "ix_team_roster_staff_timeline",
        "team_roster_memberships",
        ["staff_id", "valid_from", "valid_to"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_team_roster_staff_timeline", table_name="team_roster_memberships")
    op.drop_index("ix_team_roster_player_timeline", table_name="team_roster_memberships")
    op.drop_index("ix_team_roster_team_active", table_name="team_roster_memberships")
    op.drop_table("team_roster_memberships")
    op.drop_table("canonical_staff")
    op.drop_table("player_profiles")
    op.drop_table("team_profiles")
