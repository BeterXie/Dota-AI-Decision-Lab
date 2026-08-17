"""Add event-level AI shadow portfolio accounts and ledger.

Revision ID: 0035_ai_tournament_portfolio
Revises: 0034_access_grants_promotions
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0035_ai_tournament_portfolio"
down_revision: str | None = "0034_access_grants_promotions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_tournament_portfolios",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("canonical_event_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("prompt_version", sa.String(64), nullable=False),
        sa.Column("decision_policy_version", sa.String(64), nullable=False),
        sa.Column("ai_view_version", sa.String(32), nullable=False),
        sa.Column("initial_bankroll", sa.Numeric(14, 2), nullable=False),
        sa.Column("cash_balance", sa.Numeric(14, 2), nullable=False),
        sa.Column("locked_balance", sa.Numeric(14, 2), nullable=False),
        sa.Column("realized_pnl", sa.Numeric(14, 2), nullable=False),
        sa.Column("peak_equity", sa.Numeric(14, 2), nullable=False),
        sa.Column("max_drawdown", sa.Numeric(14, 2), nullable=False),
        sa.Column("max_drawdown_pct", sa.Float(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["canonical_event_id"],
            ["canonical_events.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "canonical_event_id",
            "provider",
            "model",
            "prompt_version",
            "decision_policy_version",
            "ai_view_version",
            name="uq_ai_tournament_portfolio_experiment",
        ),
    )
    op.create_index(
        "ix_ai_tournament_portfolio_event",
        "ai_tournament_portfolios",
        ["canonical_event_id", "status"],
    )

    op.create_table(
        "ai_tournament_positions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("portfolio_account_id", sa.Uuid(), nullable=False),
        sa.Column("ai_decision_id", sa.Uuid(), nullable=False),
        sa.Column("canonical_event_id", sa.Uuid(), nullable=False),
        sa.Column("canonical_series_id", sa.Uuid(), nullable=False),
        sa.Column("canonical_map_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("cash_before", sa.Numeric(14, 2), nullable=False),
        sa.Column("stake", sa.Numeric(14, 2), nullable=False),
        sa.Column("odds", sa.Numeric(12, 5)),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("rejection_reason", sa.String(64)),
        sa.Column("payout", sa.Numeric(14, 2)),
        sa.Column("realized_pnl", sa.Numeric(14, 2)),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("settled_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(
            ["portfolio_account_id"],
            ["ai_tournament_portfolios.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["ai_decision_id"],
            ["ai_decisions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["canonical_event_id"],
            ["canonical_events.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["canonical_series_id"],
            ["canonical_series.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["canonical_map_id"],
            ["canonical_maps.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "ai_decision_id",
            name="uq_ai_tournament_position_decision",
        ),
    )
    op.create_index(
        "ix_ai_tournament_position_account_status",
        "ai_tournament_positions",
        ["portfolio_account_id", "status"],
    )
    op.create_index(
        "ix_ai_tournament_position_map_status",
        "ai_tournament_positions",
        ["canonical_map_id", "status"],
    )

    op.create_table(
        "ai_tournament_ledger",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("portfolio_account_id", sa.Uuid(), nullable=False),
        sa.Column("position_id", sa.Uuid()),
        sa.Column("entry_type", sa.String(32), nullable=False),
        sa.Column("cash_delta", sa.Numeric(14, 2), nullable=False),
        sa.Column("locked_delta", sa.Numeric(14, 2), nullable=False),
        sa.Column("realized_pnl_delta", sa.Numeric(14, 2), nullable=False),
        sa.Column("cash_after", sa.Numeric(14, 2), nullable=False),
        sa.Column("locked_after", sa.Numeric(14, 2), nullable=False),
        sa.Column("equity_after", sa.Numeric(14, 2), nullable=False),
        sa.Column("dedupe_key", sa.String(160), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["portfolio_account_id"],
            ["ai_tournament_portfolios.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["position_id"],
            ["ai_tournament_positions.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dedupe_key", name="uq_ai_tournament_ledger_dedupe"),
    )
    op.create_index(
        "ix_ai_tournament_ledger_account_time",
        "ai_tournament_ledger",
        ["portfolio_account_id", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ai_tournament_ledger_account_time",
        table_name="ai_tournament_ledger",
    )
    op.drop_table("ai_tournament_ledger")
    op.drop_index(
        "ix_ai_tournament_position_map_status",
        table_name="ai_tournament_positions",
    )
    op.drop_index(
        "ix_ai_tournament_position_account_status",
        table_name="ai_tournament_positions",
    )
    op.drop_table("ai_tournament_positions")
    op.drop_index(
        "ix_ai_tournament_portfolio_event",
        table_name="ai_tournament_portfolios",
    )
    op.drop_table("ai_tournament_portfolios")
