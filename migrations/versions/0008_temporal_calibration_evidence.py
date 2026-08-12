"""Persist temporal calibration quality and pair evidence.

Revision ID: 0008_temporal_calibration_evidence
Revises: 0007_market_metadata_version
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_temporal_calibration_evidence"
down_revision: str | None = "0007_market_metadata_version"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "alembic_version",
        "version_num",
        existing_type=sa.String(32),
        type_=sa.String(64),
        existing_nullable=False,
    )
    op.add_column(
        "live_sync_estimates",
        sa.Column("accepted_pair_ratio", sa.Float(), nullable=False, server_default="0"),
    )
    op.add_column(
        "live_sync_estimates",
        sa.Column("ambiguous_ratio", sa.Float(), nullable=False, server_default="0"),
    )
    op.add_column(
        "live_sync_estimates",
        sa.Column("outlier_ratio", sa.Float(), nullable=False, server_default="0"),
    )
    op.create_table(
        "live_calibration_pairs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("canonical_map_id", sa.Uuid(), nullable=False),
        sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raybet_signal_id", sa.String(128), nullable=False),
        sa.Column("dltv_signal_id", sa.String(128)),
        sa.Column("raybet_received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("dltv_received_at", sa.DateTime(timezone=True)),
        sa.Column("lag_seconds", sa.Float()),
        sa.Column("raybet_signal_type", sa.String(64), nullable=False),
        sa.Column("dltv_signal_type", sa.String(64)),
        sa.Column("uniqueness_margin_seconds", sa.Float()),
        sa.Column("accepted", sa.Boolean(), nullable=False),
        sa.Column("reject_reason", sa.String(64)),
        sa.ForeignKeyConstraint(["canonical_map_id"], ["canonical_maps.id"]),
        sa.UniqueConstraint(
            "canonical_map_id",
            "calculated_at",
            "raybet_signal_id",
            name="uq_live_calibration_signal",
        ),
    )
    op.create_index(
        "ix_live_calibration_map_time",
        "live_calibration_pairs",
        ["canonical_map_id", "calculated_at"],
    )
    for column in ("accepted_pair_ratio", "ambiguous_ratio", "outlier_ratio"):
        op.alter_column("live_sync_estimates", column, server_default=None)


def downgrade() -> None:
    op.drop_index("ix_live_calibration_map_time", table_name="live_calibration_pairs")
    op.drop_table("live_calibration_pairs")
    op.drop_column("live_sync_estimates", "outlier_ratio")
    op.drop_column("live_sync_estimates", "ambiguous_ratio")
    op.drop_column("live_sync_estimates", "accepted_pair_ratio")
