from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.decision import AiDecision
from app.evaluation.portfolio_models import (
    TournamentPortfolioAccountRecord,
    TournamentPortfolioLedgerRecord,
    TournamentPortfolioPositionRecord,
)
from app.models import (
    AiDecisionRecord,
    CanonicalMap,
    CanonicalSeries,
    DecisionSnapshotRecord,
)

_MONEY = Decimal("0.01")
_ZERO = Decimal("0.00")


@dataclass(frozen=True, slots=True)
class PortfolioScope:
    canonical_event_id: UUID
    canonical_series_id: UUID
    canonical_map_id: UUID
    team_a_id: UUID
    team_b_id: UUID


@dataclass(frozen=True, slots=True)
class PortfolioContext:
    account_id: UUID
    canonical_event_id: UUID
    initial_bankroll: Decimal
    cash_balance: Decimal
    locked_balance: Decimal
    realized_pnl: Decimal
    peak_equity: Decimal
    max_drawdown: Decimal
    max_drawdown_pct: float

    @property
    def equity(self) -> Decimal:
        return _money(self.cash_balance + self.locked_balance)

    def provider_payload(self) -> dict[str, Any]:
        return {
            "scope": "CANONICAL_EVENT",
            "canonical_event_id": str(self.canonical_event_id),
            "initial": float(self.initial_bankroll),
            "bankroll_before": float(self.cash_balance),
            "cash_balance": float(self.cash_balance),
            "locked_balance": float(self.locked_balance),
            "equity": float(self.equity),
            "realized_pnl": float(self.realized_pnl),
            "units": "virtual-units",
        }


class TournamentPortfolioService:
    """Durable event-level shadow bankroll and position ledger.

    One AI experiment receives one bankroll per canonical event. BUY decisions
    reserve cash at decision-time odds; map settlement releases the position and
    rolls profit/loss into the same account used by later maps in the event.
    """

    def __init__(self, *, initial_bankroll: float = 10_000.0) -> None:
        if initial_bankroll <= 0:
            raise ValueError("initial_bankroll must be positive")
        self._initial_bankroll = _money(Decimal(str(initial_bankroll)))

    async def scope_for_snapshot(
        self,
        session: AsyncSession,
        snapshot_id: UUID,
    ) -> PortfolioScope | None:
        row = (
            await session.execute(
                select(
                    CanonicalMap.id,
                    CanonicalSeries.id,
                    CanonicalSeries.event_id,
                    CanonicalSeries.team_a_id,
                    CanonicalSeries.team_b_id,
                )
                .join(
                    DecisionSnapshotRecord,
                    DecisionSnapshotRecord.canonical_map_id == CanonicalMap.id,
                )
                .join(CanonicalSeries, CanonicalSeries.id == CanonicalMap.series_id)
                .where(DecisionSnapshotRecord.id == snapshot_id)
            )
        ).one_or_none()
        if row is None or row.event_id is None:
            return None
        return PortfolioScope(
            canonical_event_id=row.event_id,
            canonical_series_id=row.id_1,
            canonical_map_id=row.id,
            team_a_id=row.team_a_id,
            team_b_id=row.team_b_id,
        )

    async def context_for_snapshot(
        self,
        session: AsyncSession,
        *,
        snapshot_id: UUID,
        experiment: tuple[str, str, str, str, str],
    ) -> PortfolioContext | None:
        scope = await self.scope_for_snapshot(session, snapshot_id)
        if scope is None:
            return None
        account = await self._ensure_account(
            session,
            canonical_event_id=scope.canonical_event_id,
            experiment=experiment,
        )
        return _context(account)

    async def lane_scope_for_snapshot(
        self,
        session: AsyncSession,
        snapshot_id: UUID,
    ) -> str | None:
        scope = await self.scope_for_snapshot(session, snapshot_id)
        return str(scope.canonical_event_id) if scope is not None else None

    async def record_decision_position(
        self,
        session: AsyncSession,
        record: AiDecisionRecord,
    ) -> TournamentPortfolioPositionRecord | None:
        if record.parse_status != "SUCCESS" or not isinstance(record.normalized_response, dict):
            return None
        decision = AiDecision.model_validate(record.normalized_response)
        if decision.action not in {"BUY_A", "BUY_B"}:
            return None
        if record.stake is None or Decimal(record.stake) <= 0:
            return None

        existing = await session.scalar(
            select(TournamentPortfolioPositionRecord).where(
                TournamentPortfolioPositionRecord.ai_decision_id == record.id
            )
        )
        if existing is not None:
            return existing

        scope = await self.scope_for_snapshot(session, record.snapshot_id)
        if scope is None:
            return None
        experiment = (
            record.provider,
            record.model,
            record.prompt_version,
            record.decision_policy_version,
            record.ai_view_version,
        )
        await self._ensure_account(
            session,
            canonical_event_id=scope.canonical_event_id,
            experiment=experiment,
        )
        account = await session.scalar(
            select(TournamentPortfolioAccountRecord)
            .where(
                TournamentPortfolioAccountRecord.canonical_event_id
                == scope.canonical_event_id,
                TournamentPortfolioAccountRecord.provider == record.provider,
                TournamentPortfolioAccountRecord.model == record.model,
                TournamentPortfolioAccountRecord.prompt_version == record.prompt_version,
                TournamentPortfolioAccountRecord.decision_policy_version
                == record.decision_policy_version,
                TournamentPortfolioAccountRecord.ai_view_version == record.ai_view_version,
            )
            .with_for_update()
        )
        if account is None:
            raise RuntimeError("tournament portfolio account disappeared")

        snapshot = await session.get(DecisionSnapshotRecord, record.snapshot_id)
        if snapshot is None:
            raise ValueError("AI decision references a missing snapshot")
        stake = _money(Decimal(record.stake))
        odds = _selected_odds(
            snapshot.canonical_payload,
            action=decision.action,
            team_a_id=scope.team_a_id,
            team_b_id=scope.team_b_id,
        )
        rejection_reason = None
        status = "OPEN"
        if odds is None:
            status = "REJECTED"
            rejection_reason = "MISSING_DECISION_ODDS"
        elif stake > _money(account.cash_balance):
            status = "REJECTED"
            rejection_reason = "INSUFFICIENT_CASH"

        position = TournamentPortfolioPositionRecord(
            portfolio_account_id=account.id,
            ai_decision_id=record.id,
            canonical_event_id=scope.canonical_event_id,
            canonical_series_id=scope.canonical_series_id,
            canonical_map_id=scope.canonical_map_id,
            action=decision.action,
            stake=stake,
            odds=odds,
            status=status,
            rejection_reason=rejection_reason,
            opened_at=record.request_started_at,
        )
        session.add(position)
        await session.flush()
        if status == "REJECTED":
            return position

        account.cash_balance = _money(account.cash_balance - stake)
        account.locked_balance = _money(account.locked_balance + stake)
        account.updated_at = datetime.now(UTC)
        await self._ledger(
            session,
            account=account,
            position=position,
            entry_type="BET_PLACED",
            cash_delta=-stake,
            locked_delta=stake,
            realized_pnl_delta=_ZERO,
            dedupe_key=f"place:{record.id}",
            occurred_at=record.request_started_at,
        )
        return position

    async def settle_map(
        self,
        session: AsyncSession,
        *,
        canonical_map_id: UUID,
        winner_team_id: UUID | None,
        provider_conflict: bool,
        settled_at: datetime | None = None,
    ) -> int:
        canonical_map = await session.get(CanonicalMap, canonical_map_id)
        if canonical_map is None or canonical_map.series_id is None:
            return 0
        series = await session.get(CanonicalSeries, canonical_map.series_id)
        if series is None:
            return 0
        account_ids = list(
            dict.fromkeys(
                (
                    await session.scalars(
                        select(TournamentPortfolioPositionRecord.portfolio_account_id).where(
                            TournamentPortfolioPositionRecord.canonical_map_id
                            == canonical_map_id,
                            TournamentPortfolioPositionRecord.status == "OPEN",
                        )
                    )
                ).all()
            )
        )
        when = settled_at or datetime.now(UTC)
        settled = 0
        for account_id in sorted(account_ids, key=str):
            account = await session.scalar(
                select(TournamentPortfolioAccountRecord)
                .where(TournamentPortfolioAccountRecord.id == account_id)
                .with_for_update()
            )
            if account is None:
                continue
            positions = list(
                (
                    await session.scalars(
                        select(TournamentPortfolioPositionRecord)
                        .where(
                            TournamentPortfolioPositionRecord.portfolio_account_id
                            == account_id,
                            TournamentPortfolioPositionRecord.canonical_map_id
                            == canonical_map_id,
                            TournamentPortfolioPositionRecord.status == "OPEN",
                        )
                        .order_by(
                            TournamentPortfolioPositionRecord.opened_at,
                            TournamentPortfolioPositionRecord.id,
                        )
                        .with_for_update()
                    )
                ).all()
            )
            for position in positions:
                stake = _money(position.stake)
                if provider_conflict or winner_team_id is None:
                    payout = stake
                    pnl = _ZERO
                    position.status = "VOID"
                    entry_type = "BET_VOID"
                else:
                    won = (
                        position.action == "BUY_A" and winner_team_id == series.team_a_id
                    ) or (
                        position.action == "BUY_B" and winner_team_id == series.team_b_id
                    )
                    payout = (
                        _money(stake * Decimal(position.odds))
                        if won and position.odds is not None
                        else _ZERO
                    )
                    pnl = _money(payout - stake)
                    position.status = "WON" if won else "LOST"
                    entry_type = "BET_SETTLED_WIN" if won else "BET_SETTLED_LOSS"
                position.payout = payout
                position.realized_pnl = pnl
                position.settled_at = when
                account.cash_balance = _money(account.cash_balance + payout)
                account.locked_balance = _money(account.locked_balance - stake)
                account.realized_pnl = _money(account.realized_pnl + pnl)
                await self._ledger(
                    session,
                    account=account,
                    position=position,
                    entry_type=entry_type,
                    cash_delta=payout,
                    locked_delta=-stake,
                    realized_pnl_delta=pnl,
                    dedupe_key=f"settle:{position.id}",
                    occurred_at=when,
                )
                settled += 1
            if positions:
                self._update_risk(account)
                account.status = (
                    "BANKRUPT"
                    if account.cash_balance <= 0 and account.locked_balance <= 0
                    else "ACTIVE"
                )
                account.updated_at = when
        return settled

    async def leaderboard(
        self,
        session: AsyncSession,
        *,
        canonical_event_id: UUID,
    ) -> list[dict[str, Any]]:
        accounts = list(
            (
                await session.scalars(
                    select(TournamentPortfolioAccountRecord)
                    .where(
                        TournamentPortfolioAccountRecord.canonical_event_id
                        == canonical_event_id
                    )
                    .order_by(TournamentPortfolioAccountRecord.realized_pnl.desc())
                )
            ).all()
        )
        rows: list[dict[str, Any]] = []
        for account in accounts:
            positions = list(
                (
                    await session.scalars(
                        select(TournamentPortfolioPositionRecord)
                        .where(
                            TournamentPortfolioPositionRecord.portfolio_account_id
                            == account.id
                        )
                        .order_by(TournamentPortfolioPositionRecord.opened_at)
                    )
                ).all()
            )
            settled_positions = [item for item in positions if item.status in {"WON", "LOST"}]
            wins = [item for item in settled_positions if item.status == "WON"]
            losses = [item for item in settled_positions if item.status == "LOST"]
            turnover = sum((_money(item.stake) for item in settled_positions), _ZERO)
            gross_profit = sum(
                (_money(item.realized_pnl or 0) for item in wins),
                _ZERO,
            )
            gross_loss = abs(
                sum((_money(item.realized_pnl or 0) for item in losses), _ZERO)
            )
            initial = _money(account.initial_bankroll)
            equity = _money(account.cash_balance + account.locked_balance)
            rows.append(
                {
                    "account_id": str(account.id),
                    "canonical_event_id": str(account.canonical_event_id),
                    "experiment": {
                        "provider": account.provider,
                        "model": account.model,
                        "prompt_version": account.prompt_version,
                        "decision_policy_version": account.decision_policy_version,
                        "ai_view_version": account.ai_view_version,
                    },
                    "initial_bankroll": float(initial),
                    "cash_balance": float(account.cash_balance),
                    "locked_balance": float(account.locked_balance),
                    "equity": float(equity),
                    "realized_pnl": float(account.realized_pnl),
                    "roi": float(account.realized_pnl / initial) if initial > 0 else None,
                    "peak_equity": float(account.peak_equity),
                    "max_drawdown": float(account.max_drawdown),
                    "max_drawdown_pct": account.max_drawdown_pct,
                    "bet_count": len(settled_positions),
                    "open_bet_count": sum(item.status == "OPEN" for item in positions),
                    "rejected_bet_count": sum(item.status == "REJECTED" for item in positions),
                    "wins": len(wins),
                    "losses": len(losses),
                    "hit_rate": len(wins) / len(settled_positions) if settled_positions else None,
                    "turnover": float(turnover),
                    "profit_factor": (
                        float(gross_profit / gross_loss)
                        if gross_loss > 0
                        else None
                    ),
                    "status": account.status,
                }
            )
        return rows

    async def _ensure_account(
        self,
        session: AsyncSession,
        *,
        canonical_event_id: UUID,
        experiment: tuple[str, str, str, str, str],
    ) -> TournamentPortfolioAccountRecord:
        provider, model, prompt_version, decision_policy_version, ai_view_version = experiment
        predicates = (
            TournamentPortfolioAccountRecord.canonical_event_id == canonical_event_id,
            TournamentPortfolioAccountRecord.provider == provider,
            TournamentPortfolioAccountRecord.model == model,
            TournamentPortfolioAccountRecord.prompt_version == prompt_version,
            TournamentPortfolioAccountRecord.decision_policy_version
            == decision_policy_version,
            TournamentPortfolioAccountRecord.ai_view_version == ai_view_version,
        )
        account = await session.scalar(
            select(TournamentPortfolioAccountRecord).where(*predicates)
        )
        if account is not None:
            return account

        candidate = TournamentPortfolioAccountRecord(
            canonical_event_id=canonical_event_id,
            provider=provider,
            model=model,
            prompt_version=prompt_version,
            decision_policy_version=decision_policy_version,
            ai_view_version=ai_view_version,
            initial_bankroll=self._initial_bankroll,
            cash_balance=self._initial_bankroll,
            locked_balance=_ZERO,
            realized_pnl=_ZERO,
            peak_equity=self._initial_bankroll,
            max_drawdown=_ZERO,
            max_drawdown_pct=0.0,
            status="ACTIVE",
        )
        created = False
        try:
            async with session.begin_nested():
                session.add(candidate)
                await session.flush()
                created = True
        except IntegrityError:
            account = await session.scalar(
                select(TournamentPortfolioAccountRecord).where(*predicates)
            )
            if account is None:
                raise
            return account
        if not created:
            raise RuntimeError("failed to create tournament portfolio")
        await self._ledger(
            session,
            account=candidate,
            position=None,
            entry_type="EVENT_FUNDED",
            cash_delta=self._initial_bankroll,
            locked_delta=_ZERO,
            realized_pnl_delta=_ZERO,
            dedupe_key=f"fund:{candidate.id}",
            occurred_at=candidate.created_at,
        )
        return candidate

    async def _ledger(
        self,
        session: AsyncSession,
        *,
        account: TournamentPortfolioAccountRecord,
        position: TournamentPortfolioPositionRecord | None,
        entry_type: str,
        cash_delta: Decimal,
        locked_delta: Decimal,
        realized_pnl_delta: Decimal,
        dedupe_key: str,
        occurred_at: datetime,
    ) -> None:
        session.add(
            TournamentPortfolioLedgerRecord(
                portfolio_account_id=account.id,
                position_id=position.id if position is not None else None,
                entry_type=entry_type,
                cash_delta=_money(cash_delta),
                locked_delta=_money(locked_delta),
                realized_pnl_delta=_money(realized_pnl_delta),
                cash_after=_money(account.cash_balance),
                locked_after=_money(account.locked_balance),
                equity_after=_money(account.cash_balance + account.locked_balance),
                dedupe_key=dedupe_key,
                occurred_at=occurred_at,
            )
        )

    @staticmethod
    def _update_risk(account: TournamentPortfolioAccountRecord) -> None:
        equity = _money(account.cash_balance + account.locked_balance)
        peak = max(_money(account.peak_equity), equity)
        drawdown = _money(peak - equity)
        account.peak_equity = peak
        if drawdown > _money(account.max_drawdown):
            account.max_drawdown = drawdown
        drawdown_pct = float(drawdown / peak) if peak > 0 else 0.0
        if drawdown_pct > account.max_drawdown_pct:
            account.max_drawdown_pct = drawdown_pct


def _context(account: TournamentPortfolioAccountRecord) -> PortfolioContext:
    return PortfolioContext(
        account_id=account.id,
        canonical_event_id=account.canonical_event_id,
        initial_bankroll=_money(account.initial_bankroll),
        cash_balance=_money(account.cash_balance),
        locked_balance=_money(account.locked_balance),
        realized_pnl=_money(account.realized_pnl),
        peak_equity=_money(account.peak_equity),
        max_drawdown=_money(account.max_drawdown),
        max_drawdown_pct=account.max_drawdown_pct,
    )


def _selected_odds(
    payload: dict[str, Any],
    *,
    action: str,
    team_a_id: UUID,
    team_b_id: UUID,
) -> Decimal | None:
    observations = payload.get("market", {}).get("observations", [])
    target = team_a_id if action == "BUY_A" else team_b_id
    fallback: list[Decimal] = []
    for observation in observations:
        if not isinstance(observation, dict):
            continue
        raw_price = observation.get("price")
        if raw_price is None:
            continue
        try:
            price = Decimal(str(raw_price))
        except Exception:
            continue
        if price <= 1:
            continue
        fallback.append(price)
        selection_team_id = observation.get("selection_team_id")
        if selection_team_id is not None and str(selection_team_id) == str(target):
            return price
    if len(fallback) >= 2:
        return fallback[0] if action == "BUY_A" else fallback[1]
    return None


def _money(value: Decimal | int | float | str) -> Decimal:
    return Decimal(value).quantize(_MONEY, rounding=ROUND_HALF_UP)
