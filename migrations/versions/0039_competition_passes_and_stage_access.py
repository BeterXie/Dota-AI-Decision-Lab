"""Add normalized series stages and permanent event or series passes.

Revision ID: 0039_competition_passes_and_stage_access
Revises: 0038_api_performance_indexes
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0039_competition_passes_and_stage_access"
down_revision: str | None = "0038_api_performance_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "canonical_series",
        sa.Column("stage_key", sa.String(length=32), nullable=False, server_default="UNKNOWN"),
    )

    op.drop_constraint("ck_user_entitlements_scope", "user_entitlements", type_="check")
    op.create_check_constraint(
        "ck_user_entitlements_scope",
        "user_entitlements",
        "(scope_type = 'GLOBAL' AND scope_ref IS NULL) OR "
        "(scope_type IN ('EVENT', 'SERIES', 'MAP') AND scope_ref IS NOT NULL)",
    )

    op.drop_index("ix_series_pass_events_transaction", table_name="series_pass_events")
    op.drop_constraint(
        "uq_series_pass_events_provider_ref", "series_pass_events", type_="unique"
    )
    op.rename_table("series_pass_events", "competition_pass_events")
    op.alter_column(
        "competition_pass_events",
        "canonical_series_id",
        existing_type=sa.Uuid(),
        nullable=True,
    )
    op.add_column(
        "competition_pass_events",
        sa.Column("scope_type", sa.String(length=16), nullable=False, server_default="SERIES"),
    )
    op.add_column("competition_pass_events", sa.Column("canonical_event_id", sa.Uuid()))
    op.create_foreign_key(
        "fk_competition_pass_events_event",
        "competition_pass_events",
        "canonical_events",
        ["canonical_event_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_unique_constraint(
        "uq_competition_pass_events_provider_ref",
        "competition_pass_events",
        ["provider", "event_ref"],
    )
    op.create_check_constraint(
        "ck_competition_pass_event_scope",
        "competition_pass_events",
        "(scope_type = 'SERIES' AND canonical_series_id IS NOT NULL "
        "AND canonical_event_id IS NULL) OR "
        "(scope_type = 'EVENT' AND canonical_series_id IS NULL "
        "AND canonical_event_id IS NOT NULL)",
    )
    op.create_index(
        "ix_competition_pass_events_transaction",
        "competition_pass_events",
        ["provider", "transaction_ref"],
    )

    op.drop_index("ix_series_pass_purchases_customer", table_name="series_pass_purchases")
    op.drop_index("ix_series_pass_purchases_user_series", table_name="series_pass_purchases")
    op.drop_constraint(
        "uq_series_pass_purchases_provider_transaction",
        "series_pass_purchases",
        type_="unique",
    )
    op.rename_table("series_pass_purchases", "competition_pass_purchases")
    op.alter_column(
        "competition_pass_purchases",
        "canonical_series_id",
        existing_type=sa.Uuid(),
        nullable=True,
    )
    op.add_column(
        "competition_pass_purchases",
        sa.Column("scope_type", sa.String(length=16), nullable=False, server_default="SERIES"),
    )
    op.add_column("competition_pass_purchases", sa.Column("canonical_event_id", sa.Uuid()))
    op.drop_column("competition_pass_purchases", "grant_expires_at")
    op.create_foreign_key(
        "fk_competition_pass_purchases_event",
        "competition_pass_purchases",
        "canonical_events",
        ["canonical_event_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_unique_constraint(
        "uq_competition_pass_purchases_provider_transaction",
        "competition_pass_purchases",
        ["provider", "transaction_ref"],
    )
    op.create_check_constraint(
        "ck_competition_pass_purchase_scope",
        "competition_pass_purchases",
        "(scope_type = 'SERIES' AND canonical_series_id IS NOT NULL "
        "AND canonical_event_id IS NULL) OR "
        "(scope_type = 'EVENT' AND canonical_series_id IS NULL "
        "AND canonical_event_id IS NOT NULL)",
    )
    op.create_index(
        "ix_competition_pass_purchases_user_scope",
        "competition_pass_purchases",
        ["user_id", "scope_type", "canonical_series_id", "canonical_event_id", "status"],
    )
    op.create_index(
        "ix_competition_pass_purchases_customer",
        "competition_pass_purchases",
        ["provider", "customer_ref"],
    )


def downgrade() -> None:
    op.drop_index("ix_competition_pass_purchases_customer", table_name="competition_pass_purchases")
    op.drop_index(
        "ix_competition_pass_purchases_user_scope",
        table_name="competition_pass_purchases",
    )
    op.drop_constraint(
        "ck_competition_pass_purchase_scope", "competition_pass_purchases", type_="check"
    )
    op.drop_constraint(
        "uq_competition_pass_purchases_provider_transaction",
        "competition_pass_purchases",
        type_="unique",
    )
    op.drop_constraint(
        "fk_competition_pass_purchases_event", "competition_pass_purchases", type_="foreignkey"
    )
    op.add_column(
        "competition_pass_purchases",
        sa.Column("grant_expires_at", sa.DateTime(timezone=True)),
    )
    op.drop_column("competition_pass_purchases", "canonical_event_id")
    op.drop_column("competition_pass_purchases", "scope_type")
    op.alter_column(
        "competition_pass_purchases",
        "canonical_series_id",
        existing_type=sa.Uuid(),
        nullable=False,
    )
    op.rename_table("competition_pass_purchases", "series_pass_purchases")
    op.create_unique_constraint(
        "uq_series_pass_purchases_provider_transaction",
        "series_pass_purchases",
        ["provider", "transaction_ref"],
    )
    op.create_index(
        "ix_series_pass_purchases_user_series",
        "series_pass_purchases",
        ["user_id", "canonical_series_id", "status"],
    )
    op.create_index(
        "ix_series_pass_purchases_customer",
        "series_pass_purchases",
        ["provider", "customer_ref"],
    )

    op.drop_index("ix_competition_pass_events_transaction", table_name="competition_pass_events")
    op.drop_constraint(
        "ck_competition_pass_event_scope", "competition_pass_events", type_="check"
    )
    op.drop_constraint(
        "uq_competition_pass_events_provider_ref", "competition_pass_events", type_="unique"
    )
    op.drop_constraint(
        "fk_competition_pass_events_event", "competition_pass_events", type_="foreignkey"
    )
    op.drop_column("competition_pass_events", "canonical_event_id")
    op.drop_column("competition_pass_events", "scope_type")
    op.alter_column(
        "competition_pass_events",
        "canonical_series_id",
        existing_type=sa.Uuid(),
        nullable=False,
    )
    op.rename_table("competition_pass_events", "series_pass_events")
    op.create_unique_constraint(
        "uq_series_pass_events_provider_ref",
        "series_pass_events",
        ["provider", "event_ref"],
    )
    op.create_index(
        "ix_series_pass_events_transaction",
        "series_pass_events",
        ["provider", "transaction_ref"],
    )

    op.drop_constraint("ck_user_entitlements_scope", "user_entitlements", type_="check")
    op.create_check_constraint(
        "ck_user_entitlements_scope",
        "user_entitlements",
        "(scope_type = 'GLOBAL' AND scope_ref IS NULL) OR "
        "(scope_type IN ('SERIES', 'MAP') AND scope_ref IS NOT NULL)",
    )
    op.drop_column("canonical_series", "stage_key")
