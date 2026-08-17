"""Add external authentication identities for Google and Steam.

Revision ID: 0036_external_auth_identities
Revises: 0035_ai_tournament_portfolio
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0036_external_auth_identities"
down_revision: str | None = "0035_ai_tournament_portfolio"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("user_accounts", "email", existing_type=sa.String(length=320), nullable=True)
    op.alter_column(
        "user_accounts",
        "email_verified_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=True,
    )
    op.add_column("user_accounts", sa.Column("display_name", sa.String(length=160), nullable=True))
    op.add_column("user_accounts", sa.Column("avatar_url", sa.Text(), nullable=True))

    op.create_table(
        "external_identities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("provider_email", sa.String(length=320), nullable=True),
        sa.Column("display_name", sa.String(length=160), nullable=True),
        sa.Column("avatar_url", sa.Text(), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user_accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "subject", name="uq_external_identity_provider_subject"),
    )
    op.create_index(
        "ix_external_identity_user",
        "external_identities",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_external_identity_user", table_name="external_identities")
    op.drop_table("external_identities")
    op.drop_column("user_accounts", "avatar_url")
    op.drop_column("user_accounts", "display_name")
    # The pre-social schema requires an email. Do not fabricate addresses for
    # Steam-only users during downgrade; remove accounts that cannot exist there.
    op.execute("DELETE FROM user_accounts WHERE email IS NULL")
    op.alter_column(
        "user_accounts",
        "email_verified_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
    )
    op.alter_column("user_accounts", "email", existing_type=sa.String(length=320), nullable=False)
