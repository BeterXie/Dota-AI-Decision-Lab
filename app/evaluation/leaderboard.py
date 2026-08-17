from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.evaluation.portfolio_models import (
    TournamentPortfolioAccountRecord,
    TournamentPortfolioPositionRecord,
)
from app.models import CanonicalEvent

_ZERO = Decimal("0")
ExperimentKey = tuple[str, str, str, str, str]


class TournamentLeaderboardService:
    """Aggregate independently funded event portfolios by AI experiment."""

    async def build_report(self, session: AsyncSession) -> dict[str, Any]:
        account_rows = list(
            (
                await session.execute(
                    select(TournamentPortfolioAccountRecord, CanonicalEvent)
                    .join(
                        CanonicalEvent,
                        CanonicalEvent.id == TournamentPortfolioAccountRecord.canonical_event_id,
                    )
                    .order_by(
                        TournamentPortfolioAccountRecord.provider,
                        TournamentPortfolioAccountRecord.model,
                        TournamentPortfolioAccountRecord.prompt_version,
                        CanonicalEvent.started_at,
                        CanonicalEvent.name,
                    )
                )
            ).all()
        )
        if not account_rows:
            return {
                "scope": "ALL_CANONICAL_EVENTS",
                "ranking": "REALIZED_ROI_THEN_PNL",
                "experiments": [],
            }

        account_ids = [account.id for account, _ in account_rows]
        positions = list(
            (
                await session.scalars(
                    select(TournamentPortfolioPositionRecord).where(
                        TournamentPortfolioPositionRecord.portfolio_account_id.in_(account_ids)
                    )
                )
            ).all()
        )
        positions_by_account: dict[Any, list[TournamentPortfolioPositionRecord]] = defaultdict(list)
        for position in positions:
            positions_by_account[position.portfolio_account_id].append(position)

        grouped: dict[
            ExperimentKey, list[tuple[TournamentPortfolioAccountRecord, CanonicalEvent]]
        ] = defaultdict(list)
        for account, event in account_rows:
            grouped[_experiment_key(account)].append((account, event))

        experiments = [
            _aggregate_experiment(rows, positions_by_account) for rows in grouped.values()
        ]
        experiments.sort(
            key=lambda row: (
                -float(row["realized_roi"]),
                -float(row["realized_pnl"]),
                float(row["worst_event_drawdown_pct"]),
                row["experiment"]["provider"],
                row["experiment"]["model"],
            )
        )
        for rank, row in enumerate(experiments, start=1):
            row["rank"] = rank
        return {
            "scope": "ALL_CANONICAL_EVENTS",
            "ranking": "REALIZED_ROI_THEN_PNL",
            "experiments": experiments,
        }


def _aggregate_experiment(
    rows: list[tuple[TournamentPortfolioAccountRecord, CanonicalEvent]],
    positions_by_account: dict[Any, list[TournamentPortfolioPositionRecord]],
) -> dict[str, Any]:
    first = rows[0][0]
    initial = sum((Decimal(account.initial_bankroll) for account, _ in rows), _ZERO)
    pnl = sum((Decimal(account.realized_pnl) for account, _ in rows), _ZERO)
    cash = sum((Decimal(account.cash_balance) for account, _ in rows), _ZERO)
    locked = sum((Decimal(account.locked_balance) for account, _ in rows), _ZERO)
    profitable_events = sum(Decimal(account.realized_pnl) > 0 for account, _ in rows)
    losing_events = sum(Decimal(account.realized_pnl) < 0 for account, _ in rows)
    flat_events = len(rows) - profitable_events - losing_events
    bankrupt_events = sum(account.status == "BANKRUPT" for account, _ in rows)

    all_positions = [
        position for account, _ in rows for position in positions_by_account.get(account.id, ())
    ]
    settled = [position for position in all_positions if position.status in {"WON", "LOST"}]
    wins = [position for position in settled if position.status == "WON"]
    losses = [position for position in settled if position.status == "LOST"]
    turnover = sum((Decimal(position.stake) for position in settled), _ZERO)
    gross_profit = sum(
        (Decimal(position.realized_pnl or 0) for position in wins),
        _ZERO,
    )
    gross_loss = abs(sum((Decimal(position.realized_pnl or 0) for position in losses), _ZERO))

    event_breakdown = []
    for account, event in sorted(
        rows,
        key=lambda item: (
            item[1].started_at is None,
            item[1].started_at,
            item[1].name,
        ),
    ):
        event_initial = Decimal(account.initial_bankroll)
        event_pnl = Decimal(account.realized_pnl)
        event_equity = Decimal(account.cash_balance) + Decimal(account.locked_balance)
        event_breakdown.append(
            {
                "canonical_event_id": str(account.canonical_event_id),
                "event_name": event.name,
                "started_at": event.started_at,
                "ended_at": event.ended_at,
                "initial_bankroll": float(event_initial),
                "equity": float(event_equity),
                "realized_pnl": float(event_pnl),
                "realized_roi": float(event_pnl / event_initial) if event_initial > 0 else None,
                "max_drawdown_pct": account.max_drawdown_pct,
                "status": account.status,
            }
        )

    return {
        "rank": None,
        "experiment": {
            "provider": first.provider,
            "model": first.model,
            "prompt_version": first.prompt_version,
            "decision_policy_version": first.decision_policy_version,
            "ai_view_version": first.ai_view_version,
        },
        "event_count": len(rows),
        "total_initial_bankroll": float(initial),
        "cash_balance": float(cash),
        "locked_balance": float(locked),
        "equity": float(cash + locked),
        "realized_pnl": float(pnl),
        "realized_roi": float(pnl / initial) if initial > 0 else 0.0,
        "profitable_events": profitable_events,
        "losing_events": losing_events,
        "flat_events": flat_events,
        "profitable_event_rate": profitable_events / len(rows),
        "bankrupt_events": bankrupt_events,
        "worst_event_drawdown_pct": max(account.max_drawdown_pct for account, _ in rows),
        "bet_count": len(settled),
        "open_bet_count": sum(position.status == "OPEN" for position in all_positions),
        "rejected_bet_count": sum(position.status == "REJECTED" for position in all_positions),
        "wins": len(wins),
        "losses": len(losses),
        "hit_rate": len(wins) / len(settled) if settled else None,
        "turnover": float(turnover),
        "profit_factor": float(gross_profit / gross_loss) if gross_loss > 0 else None,
        "events": event_breakdown,
    }


def _experiment_key(account: TournamentPortfolioAccountRecord) -> ExperimentKey:
    return (
        account.provider,
        account.model,
        account.prompt_version,
        account.decision_policy_version,
        account.ai_view_version,
    )
