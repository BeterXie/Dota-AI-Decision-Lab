from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Float, ForeignKey, Index, Numeric, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.domain.experiment import STATIC_EXECUTION_CONFIG_VERSION


def utc_now() -> datetime:
    return datetime.now(UTC)


class TournamentPortfolioAccountRecord(Base):
    """Materialized balance for one AI experiment inside one canonical event."""

    __tablename__ = "ai_tournament_portfolios"
    __table_args__ = (
        UniqueConstraint(
            "canonical_event_id",
            "provider",
            "model",
            "prompt_version",
            "decision_policy_version",
            "ai_view_version",
            "execution_config_version",
            name="uq_ai_tournament_portfolio_experiment",
        ),
        Index("ix_ai_tournament_portfolio_event", "canonical_event_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    canonical_event_id: Mapped[UUID] = mapped_column(
        ForeignKey("canonical_events.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    decision_policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    ai_view_version: Mapped[str] = mapped_column(String(32), nullable=False)
    execution_config_version: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        default=STATIC_EXECUTION_CONFIG_VERSION,
    )
    initial_bankroll: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    cash_balance: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    locked_balance: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    realized_pnl: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    peak_equity: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    max_drawdown: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    max_drawdown_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class TournamentPortfolioPositionRecord(Base):
    """One executable virtual BUY decision at frozen decision-time odds."""

    __tablename__ = "ai_tournament_positions"
    __table_args__ = (
        UniqueConstraint("ai_decision_id", name="uq_ai_tournament_position_decision"),
        Index("ix_ai_tournament_position_account_status", "portfolio_account_id", "status"),
        Index("ix_ai_tournament_position_map_status", "canonical_map_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    portfolio_account_id: Mapped[UUID] = mapped_column(
        ForeignKey("ai_tournament_portfolios.id", ondelete="CASCADE"), nullable=False
    )
    ai_decision_id: Mapped[UUID] = mapped_column(
        ForeignKey("ai_decisions.id", ondelete="CASCADE"), nullable=False
    )
    canonical_event_id: Mapped[UUID] = mapped_column(
        ForeignKey("canonical_events.id", ondelete="CASCADE"), nullable=False
    )
    canonical_series_id: Mapped[UUID] = mapped_column(
        ForeignKey("canonical_series.id", ondelete="CASCADE"), nullable=False
    )
    canonical_map_id: Mapped[UUID] = mapped_column(
        ForeignKey("canonical_maps.id", ondelete="CASCADE"), nullable=False
    )
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    cash_before: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    stake: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    odds: Mapped[Decimal | None] = mapped_column(Numeric(12, 5))
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    rejection_reason: Mapped[str | None] = mapped_column(String(64))
    payout: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    realized_pnl: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TournamentPortfolioLedgerRecord(Base):
    """Append-only cash/locked-capital audit event for a tournament portfolio."""

    __tablename__ = "ai_tournament_ledger"
    __table_args__ = (
        UniqueConstraint("dedupe_key", name="uq_ai_tournament_ledger_dedupe"),
        Index("ix_ai_tournament_ledger_account_time", "portfolio_account_id", "occurred_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    portfolio_account_id: Mapped[UUID] = mapped_column(
        ForeignKey("ai_tournament_portfolios.id", ondelete="CASCADE"), nullable=False
    )
    position_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("ai_tournament_positions.id", ondelete="SET NULL")
    )
    entry_type: Mapped[str] = mapped_column(String(32), nullable=False)
    cash_delta: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    locked_delta: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    realized_pnl_delta: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    cash_after: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    locked_after: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    equity_after: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(160), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
