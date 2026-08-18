"""Add database-backed runtime configuration and encrypted secrets.

Revision ID: 0038_runtime_configuration
Revises: 0037_team_roster_registry
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0038_runtime_configuration"
down_revision: str | None = "0037_team_roster_registry"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JSON_DOCUMENT = sa.JSON().with_variant(JSONB(), "postgresql")


def upgrade() -> None:
    # PostgreSQL pgcrypto keeps provider/OAuth credentials encrypted at rest
    # without adding an application crypto dependency. The master passphrase is
    # still a bootstrap secret and is never persisted in these tables.
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    op.create_table(
        "runtime_settings",
        sa.Column("key", sa.String(length=160), nullable=False),
        sa.Column("value", _JSON_DOCUMENT, nullable=False),
        sa.Column("value_type", sa.String(length=24), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("updated_by", sa.String(length=320), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )
    op.create_table(
        "runtime_secrets",
        sa.Column("key", sa.String(length=160), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("updated_by", sa.String(length=320), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )
    op.create_table(
        "ai_provider_configs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("slot", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("decisions_enabled", sa.Boolean(), nullable=False),
        sa.Column("base_url", sa.Text(), nullable=False),
        sa.Column("model", sa.String(length=160), nullable=False),
        sa.Column("reasoning_effort", sa.String(length=32), nullable=True),
        sa.Column("timeout_seconds", sa.Float(), nullable=False),
        sa.Column("api_key_secret_key", sa.String(length=160), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("updated_by", sa.String(length=320), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "slot", name="uq_ai_provider_config_slot"),
        sa.UniqueConstraint("provider", "model", name="uq_ai_provider_config_model"),
    )
    op.create_table(
        "runtime_config_audit",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("target_key", sa.String(length=200), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("operation", sa.String(length=32), nullable=False),
        sa.Column("previous_value", _JSON_DOCUMENT, nullable=True),
        sa.Column("new_value", _JSON_DOCUMENT, nullable=True),
        sa.Column("secret_changed", sa.Boolean(), nullable=False),
        sa.Column("actor", sa.String(length=320), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_runtime_config_audit_target_key",
        "runtime_config_audit",
        ["target_key"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_runtime_config_audit_target_key", table_name="runtime_config_audit")
    op.drop_table("runtime_config_audit")
    op.drop_table("ai_provider_configs")
    op.drop_table("runtime_secrets")
    op.drop_table("runtime_settings")
