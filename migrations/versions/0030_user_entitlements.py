"""Add user-scoped premium entitlement grants.

Revision ID: 0030_user_entitlements
Revises: 0029_email_auth
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0030_user_entitlements"
down_revision: str | None = "0029_email_auth"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_entitlements",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("entitlement", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("source", sa.String(length=128), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user_accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "entitlement",
            "source",
            name="uq_user_entitlements_user_entitlement_source",
        ),
    )
    op.create_index(
        "ix_user_entitlements_access",
        "user_entitlements",
        ["user_id", "entitlement", "status"],
        unique=False,
    )
    op.create_index(
        "ix_user_entitlements_expiry",
        "user_entitlements",
        ["expires_at", "status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_user_entitlements_expiry", table_name="user_entitlements")
    op.drop_index("ix_user_entitlements_access", table_name="user_entitlements")
    op.drop_table("user_entitlements")
