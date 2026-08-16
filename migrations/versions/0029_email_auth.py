"""Add passwordless email authentication tables.

Revision ID: 0029_email_auth
Revises: 0028_historical_start_time_provenance
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0029_email_auth"
down_revision: str | None = "0028_historical_start_time_provenance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_accounts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_index("ix_user_accounts_email", "user_accounts", ["email"], unique=True)

    op.create_table(
        "email_login_challenges",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("code_digest", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivery_status", sa.String(length=16), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_email_login_challenge_email_created",
        "email_login_challenges",
        ["email", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_email_login_challenge_expiry",
        "email_login_challenges",
        ["expires_at", "consumed_at"],
        unique=False,
    )

    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_digest", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user_accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_digest"),
    )
    op.create_index(
        "ix_auth_sessions_token_digest", "auth_sessions", ["token_digest"], unique=True
    )
    op.create_index(
        "ix_auth_session_user_expiry",
        "auth_sessions",
        ["user_id", "expires_at"],
        unique=False,
    )
    op.create_index(
        "ix_auth_session_expiry_revoked",
        "auth_sessions",
        ["expires_at", "revoked_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_auth_session_expiry_revoked", table_name="auth_sessions")
    op.drop_index("ix_auth_session_user_expiry", table_name="auth_sessions")
    op.drop_index("ix_auth_sessions_token_digest", table_name="auth_sessions")
    op.drop_table("auth_sessions")
    op.drop_index("ix_email_login_challenge_expiry", table_name="email_login_challenges")
    op.drop_index("ix_email_login_challenge_email_created", table_name="email_login_challenges")
    op.drop_table("email_login_challenges")
    op.drop_index("ix_user_accounts_email", table_name="user_accounts")
    op.drop_table("user_accounts")
