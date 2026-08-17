"""Add server-owned billing checkout mappings.

Revision ID: 0033_billing_checkouts
Revises: 0032_billing_lifecycle
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0033_billing_checkouts"
down_revision: str | None = "0032_billing_lifecycle"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "billing_checkouts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("checkout_ref", sa.String(160), nullable=False),
        sa.Column("customer_ref", sa.String(160)),
        sa.Column("offer_key", sa.String(64), nullable=False),
        sa.Column("price_ref", sa.String(160), nullable=False),
        sa.Column("plan_key", sa.String(64), nullable=False),
        sa.Column("recurring", sa.Boolean(), nullable=False),
        sa.Column("grant_days", sa.Integer()),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user_accounts.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "provider",
            "checkout_ref",
            name="uq_billing_checkouts_provider_ref",
        ),
    )
    op.create_index(
        "ix_billing_checkouts_user_created",
        "billing_checkouts",
        ["user_id", "created_at"],
    )
    op.create_index(
        "ix_billing_checkouts_customer",
        "billing_checkouts",
        ["provider", "customer_ref"],
    )


def downgrade() -> None:
    op.drop_index("ix_billing_checkouts_customer", table_name="billing_checkouts")
    op.drop_index("ix_billing_checkouts_user_created", table_name="billing_checkouts")
    op.drop_table("billing_checkouts")
