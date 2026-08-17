"""Add scoped access grants, referrals, and canonical-series purchases.

Revision ID: 0034_access_grants_promotions
Revises: 0033_billing_checkouts
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0034_access_grants_promotions"
down_revision: str | None = "0033_billing_checkouts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "user_entitlements",
        sa.Column("scope_type", sa.String(16), nullable=False, server_default="GLOBAL"),
    )
    op.add_column("user_entitlements", sa.Column("scope_ref", sa.Uuid()))
    op.add_column("user_entitlements", sa.Column("campaign_key", sa.String(64)))
    op.create_check_constraint(
        "ck_user_entitlements_scope",
        "user_entitlements",
        "(scope_type = 'GLOBAL' AND scope_ref IS NULL) OR "
        "(scope_type IN ('SERIES', 'MAP') AND scope_ref IS NOT NULL)",
    )
    op.create_index(
        "ix_user_entitlements_scoped_access",
        "user_entitlements",
        ["user_id", "entitlement", "scope_type", "scope_ref", "status"],
    )
    op.create_index(
        "ix_user_entitlements_campaign",
        "user_entitlements",
        ["campaign_key", "status"],
    )

    op.create_table(
        "referral_codes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user_accounts.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", name="uq_referral_codes_user"),
        sa.UniqueConstraint("code", name="uq_referral_codes_code"),
    )
    op.create_index("ix_referral_codes_status", "referral_codes", ["status"])

    op.create_table(
        "referral_attributions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("inviter_user_id", sa.Uuid(), nullable=False),
        sa.Column("invited_user_id", sa.Uuid(), nullable=False),
        sa.Column("referral_code_id", sa.Uuid(), nullable=False),
        sa.Column("campaign_key", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("qualified_provider", sa.String(32)),
        sa.Column("qualified_payment_ref", sa.String(160)),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("qualified_at", sa.DateTime(timezone=True)),
        sa.Column("rewarded_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["inviter_user_id"], ["user_accounts.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["invited_user_id"], ["user_accounts.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["referral_code_id"], ["referral_codes.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("invited_user_id", name="uq_referral_attributions_invited_user"),
        sa.UniqueConstraint(
            "qualified_provider",
            "qualified_payment_ref",
            name="uq_referral_attributions_payment",
        ),
    )
    op.create_index(
        "ix_referral_attributions_inviter",
        "referral_attributions",
        ["inviter_user_id", "status"],
    )
    op.create_index(
        "ix_referral_attributions_campaign",
        "referral_attributions",
        ["campaign_key", "status"],
    )

    op.create_table(
        "series_pass_purchases",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("transaction_ref", sa.String(160), nullable=False),
        sa.Column("customer_ref", sa.String(160)),
        sa.Column("canonical_series_id", sa.Uuid(), nullable=False),
        sa.Column("price_ref", sa.String(160), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("payment_blocked", sa.Boolean(), nullable=False),
        sa.Column("grant_expires_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("last_event_occurred_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user_accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["canonical_series_id"], ["canonical_series.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "provider",
            "transaction_ref",
            name="uq_series_pass_purchases_provider_transaction",
        ),
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

    op.create_table(
        "series_pass_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("event_ref", sa.String(160), nullable=False),
        sa.Column("transaction_ref", sa.String(160), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("canonical_series_id", sa.Uuid(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload_digest", sa.String(64), nullable=False),
        sa.Column("applied", sa.Boolean(), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user_accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["canonical_series_id"], ["canonical_series.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "provider", "event_ref", name="uq_series_pass_events_provider_ref"
        ),
    )
    op.create_index(
        "ix_series_pass_events_transaction",
        "series_pass_events",
        ["provider", "transaction_ref"],
    )


def downgrade() -> None:
    op.drop_index("ix_series_pass_events_transaction", table_name="series_pass_events")
    op.drop_table("series_pass_events")
    op.drop_index("ix_series_pass_purchases_customer", table_name="series_pass_purchases")
    op.drop_index("ix_series_pass_purchases_user_series", table_name="series_pass_purchases")
    op.drop_table("series_pass_purchases")
    op.drop_index("ix_referral_attributions_campaign", table_name="referral_attributions")
    op.drop_index("ix_referral_attributions_inviter", table_name="referral_attributions")
    op.drop_table("referral_attributions")
    op.drop_index("ix_referral_codes_status", table_name="referral_codes")
    op.drop_table("referral_codes")
    op.drop_index("ix_user_entitlements_campaign", table_name="user_entitlements")
    op.drop_index("ix_user_entitlements_scoped_access", table_name="user_entitlements")
    op.drop_constraint("ck_user_entitlements_scope", "user_entitlements", type_="check")
    op.drop_column("user_entitlements", "campaign_key")
    op.drop_column("user_entitlements", "scope_ref")
    op.drop_column("user_entitlements", "scope_type")
