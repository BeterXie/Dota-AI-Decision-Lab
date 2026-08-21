from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.decision import AiDecision
from app.domain.experiment import AiExperimentKey
from app.evaluation.portfolio_models import (
    TournamentPortfolioAccountRecord,
    TournamentPortfolioLedgerRecord,
    TournamentPortfolioPositionRecord,
)
from app.models import (
    AiDecisionRecord,
    CanonicalEvent,
    CanonicalMap,
    CanonicalSeries,
    DecisionSnapshotRecord,
    MapResultRecord,
)
from app.time import ensure_utc

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
                    CanonicalMap.id.label("canonical_map_id"),
                    CanonicalSeries.id.label("canonical_series_id"),
                    CanonicalSeries.event_id.label("canonical_event_id"),
                    CanonicalSeries.team_a_id.label("team_a_id"),
                    CanonicalSeries.team_b_id.label("team_b_id"),
                )
                .join(
                    DecisionSnapshotRecord,
                    DecisionSnapshotRecord.canonical_map_id == CanonicalMap.id,
                )
                .join(CanonicalSeries, CanonicalSeries.id == CanonicalMap.series_id)
                .where(DecisionSnapshotRecord.id == snapshot_id)
            )
        ).one_or_none()
        if row is None or row.canonical_event_id is None:
            return None
        return PortfolioScope(
            canonical_event_id=row.canonical_event_id,
            canonical_series_id=row.canonical_series_id,
            canonical_map_id=row.canonical_map_id,
            team_a_id=row.team_a_id,
            team_b_id=row.team_b_id,
        )

    async def context_for_snapshot(
        self,
        session: AsyncSession,
        *,
        snapshot_id: UUID,
        experiment: AiExperimentKey,
    ) -> PortfolioContext | None:
        scope = await self.scope_for_snapshot(session, snapshot_id)
        if scope is None:
            return None
        snapshot = await session.get(DecisionSnapshotRecord, snapshot_id)
        return await self.context_for_scope(
            session,
            scope=scope,
            experiment=experiment,
            funding_reference_at=snapshot.decision_at if snapshot is not None else None,
        )

    async def context_for_scope(
        self,
        session: AsyncSession,
        *,
        scope: PortfolioScope,
        experiment: AiExperimentKey,
        funding_reference_at: datetime | None = None,
    ) -> PortfolioContext:
        account = await self._ensure_account(
            session,
            canonical_event_id=scope.canonical_event_id,
            experiment=experiment,
            funding_reference_at=funding_reference_at,
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
        *,
        scope: PortfolioScope | None = None,
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

        if scope is None:
            scope = await self.scope_for_snapshot(session, record.snapshot_id)
        if scope is None:
            return None
        snapshot = await session.get(DecisionSnapshotRecord, record.snapshot_id)
        if snapshot is None:
            raise ValueError("AI decision references a missing snapshot")
        experiment = (
            record.provider,
            record.model,
            record.prompt_version,
            record.decision_policy_version,
            record.ai_view_version,
            record.execution_config_version,
        )
        await self._ensure_account(
            session,
            canonical_event_id=scope.canonical_event_id,
            experiment=experiment,
            funding_reference_at=snapshot.decision_at,
        )
        account = await session.scalar(
            select(TournamentPortfolioAccountRecord)
            .where(
                TournamentPortfolioAccountRecord.canonical_event_id == scope.canonical_event_id,
                TournamentPortfolioAccountRecord.provider == record.provider,
                TournamentPortfolioAccountRecord.model == record.model,
                TournamentPortfolioAccountRecord.prompt_version == record.prompt_version,
                TournamentPortfolioAccountRecord.decision_policy_version
                == record.decision_policy_version,
                TournamentPortfolioAccountRecord.ai_view_version == record.ai_view_version,
                TournamentPortfolioAccountRecord.execution_config_version
                == record.execution_config_version,
            )
            .with_for_update()
        )
        if account is None:
            raise RuntimeError("tournament portfolio account disappeared")
        existing = await session.scalar(
            select(TournamentPortfolioPositionRecord).where(
                TournamentPortfolioPositionRecord.ai_decision_id == record.id
            )
        )
        if existing is not None:
            return existing

        stake = _money(Decimal(record.stake))
        odds = _selected_odds(
            snapshot.canonical_payload,
            action=decision.action,
            team_a_id=scope.team_a_id,
            team_b_id=scope.team_b_id,
        )
        result = await session.scalar(
            select(MapResultRecord).where(
                MapResultRecord.canonical_map_id == scope.canonical_map_id
            )
        )
        cash_before = _money(account.cash_balance)
        decision_available_at = ensure_utc(
            record.response_received_at or record.decision_persisted_at or record.request_started_at
        )
        rejection_reason = None
        status = "OPEN"
        execution_quality_rejection = _execution_quality_rejection(snapshot.canonical_payload)
        if result is not None and ensure_utc(result.basic_first_usable_at) <= decision_available_at:
            status = "REJECTED"
            rejection_reason = "MAP_ALREADY_SETTLED"
        elif execution_quality_rejection is not None:
            status = "REJECTED"
            rejection_reason = execution_quality_rejection
        elif odds is None:
            status = "REJECTED"
            rejection_reason = "MISSING_DECISION_ODDS"
        elif stake > cash_before:
            status = "REJECTED"
            rejection_reason = "INSUFFICIENT_CASH"

        position = TournamentPortfolioPositionRecord(
            portfolio_account_id=account.id,
            ai_decision_id=record.id,
            canonical_event_id=scope.canonical_event_id,
            canonical_series_id=scope.canonical_series_id,
            canonical_map_id=scope.canonical_map_id,
            action=decision.action,
            cash_before=cash_before,
            stake=stake,
            odds=odds,
            status=status,
            rejection_reason=rejection_reason,
            opened_at=decision_available_at,
        )
        session.add(position)
        await session.flush()
        if status == "REJECTED":
            return position

        account.cash_balance = _money(cash_before - stake)
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
            occurred_at=decision_available_at,
        )
        if result is not None:
            await self.settle_map(
                session,
                canonical_map_id=scope.canonical_map_id,
                winner_team_id=result.winner_team_id,
                provider_conflict=bool(result.provider_conflict),
                settled_at=result.settled_at,
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
                            TournamentPortfolioPositionRecord.canonical_map_id == canonical_map_id,
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
                            TournamentPortfolioPositionRecord.portfolio_account_id == account_id,
                            TournamentPortfolioPositionRecord.canonical_map_id == canonical_map_id,
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
                winner_is_valid = winner_team_id in {series.team_a_id, series.team_b_id}
                if provider_conflict or not winner_is_valid:
                    payout = stake
                    pnl = _ZERO
                    position.status = "VOID"
                    entry_type = "BET_VOID"
                else:
                    won = (position.action == "BUY_A" and winner_team_id == series.team_a_id) or (
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
                        TournamentPortfolioAccountRecord.canonical_event_id == canonical_event_id
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
                        .where(TournamentPortfolioPositionRecord.portfolio_account_id == account.id)
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
            gross_loss = abs(sum((_money(item.realized_pnl or 0) for item in losses), _ZERO))
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
                        "execution_config_version": account.execution_config_version,
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
                    "profit_factor": (float(gross_profit / gross_loss) if gross_loss > 0 else None),
                    "status": account.status,
                }
            )
        return rows

    async def _ensure_account(
        self,
        session: AsyncSession,
        *,
        canonical_event_id: UUID,
        experiment: AiExperimentKey,
        funding_reference_at: datetime | None = None,
    ) -> TournamentPortfolioAccountRecord:
        (
            provider,
            model,
            prompt_version,
            decision_policy_version,
            ai_view_version,
            execution_config_version,
        ) = experiment
        predicates = (
            TournamentPortfolioAccountRecord.canonical_event_id == canonical_event_id,
            TournamentPortfolioAccountRecord.provider == provider,
            TournamentPortfolioAccountRecord.model == model,
            TournamentPortfolioAccountRecord.prompt_version == prompt_version,
            TournamentPortfolioAccountRecord.decision_policy_version == decision_policy_version,
            TournamentPortfolioAccountRecord.ai_view_version == ai_view_version,
            TournamentPortfolioAccountRecord.execution_config_version == execution_config_version,
        )
        account = await session.scalar(select(TournamentPortfolioAccountRecord).where(*predicates))
        if account is not None:
            return account

        event = await session.get(CanonicalEvent, canonical_event_id)
        event_started_at = (
            ensure_utc(event.started_at)
            if event is not None and event.started_at is not None
            else None
        )
        reference_at = (
            ensure_utc(funding_reference_at) if funding_reference_at is not None else None
        )
        if event_started_at is not None and reference_at is not None:
            funded_at = min(event_started_at, reference_at)
        else:
            funded_at = event_started_at or reference_at or datetime.now(UTC)
        candidate = TournamentPortfolioAccountRecord(
            canonical_event_id=canonical_event_id,
            provider=provider,
            model=model,
            prompt_version=prompt_version,
            decision_policy_version=decision_policy_version,
            ai_view_version=ai_view_version,
            execution_config_version=execution_config_version,
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
            occurred_at=funded_at,
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


def _execution_quality_rejection(payload: dict[str, Any]) -> str | None:
    snapshot_quality = payload.get("quality")
    if not isinstance(snapshot_quality, dict) or snapshot_quality.get("eligible") is not True:
        return "SNAPSHOT_NOT_EXECUTABLE"
    market = payload.get("market")
    if not isinstance(market, dict):
        return "MARKET_NOT_EXECUTABLE"
    market_quality = market.get("quality")
    if not isinstance(market_quality, dict) or market_quality.get("eligible") is not True:
        return "MARKET_NOT_EXECUTABLE"
    return None


def _selected_odds(
    payload: dict[str, Any],
    *,
    action: str,
    team_a_id: UUID,
    team_b_id: UUID,
) -> Decimal | None:
    market = payload.get("market")
    if not isinstance(market, dict):
        return None
    observations = market.get("observations")
    if not isinstance(observations, list):
        return None
    target = team_a_id if action == "BUY_A" else team_b_id
    for observation in observations:
        if not isinstance(observation, dict):
            continue
        selection_team_id = observation.get("selection_team_id")
        if selection_team_id is None or str(selection_team_id) != str(target):
            continue
        raw_price = observation.get("price")
        if raw_price is None:
            return None
        try:
            price = Decimal(str(raw_price))
        except InvalidOperation, ValueError:
            return None
        return price if price > 1 else None
    return None


def _money(value: Decimal | int | float | str) -> Decimal:
    return Decimal(value).quantize(_MONEY, rounding=ROUND_HALF_UP)
