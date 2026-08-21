from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.decision import AiDecision
from app.evaluation.latency import LatencyExecutionService
from app.evaluation.metrics import brier_score, log_loss
from app.evaluation.portfolio import TournamentPortfolioService
from app.evaluation.portfolio_models import (
    TournamentPortfolioLedgerRecord,
    TournamentPortfolioPositionRecord,
)
from app.models import (
    AiDecisionRecord,
    CanonicalMap,
    CanonicalSeries,
    DecisionEvaluationRecord,
    DecisionSnapshotRecord,
    MapResultRecord,
)

QUALITY_REPORT_VERSION = "tournament-quality-v1"
QUALITY_GATE_MODE = "SHADOW_ONLY"


@dataclass(frozen=True, slots=True)
class QualityGatePolicy:
    min_settled_maps: int = 20
    min_settled_bets: int = 10
    min_prediction_samples: int = 20
    min_clv_samples: int = 10
    min_market_comparison_samples: int = 20
    min_roi: float = 0.0
    min_average_clv: float = 0.0
    min_brier_improvement_vs_market: float = 0.0
    max_drawdown_pct: float = 0.30


class TournamentQualityService:
    """Evaluate one event's AI experiments without controlling production yet."""

    def __init__(
        self,
        portfolio: TournamentPortfolioService | None = None,
        *,
        policy: QualityGatePolicy | None = None,
    ) -> None:
        self._portfolio = portfolio or TournamentPortfolioService()
        self._policy = policy or QualityGatePolicy()
        self._latency = LatencyExecutionService()

    async def build_report(
        self,
        session: AsyncSession,
        *,
        canonical_event_id: UUID,
    ) -> dict[str, Any]:
        portfolio_rows = await self._portfolio.leaderboard(
            session,
            canonical_event_id=canonical_event_id,
        )
        experiments = []
        for portfolio_row in portfolio_rows:
            experiments.append(
                await self._experiment_report(
                    session,
                    canonical_event_id=canonical_event_id,
                    portfolio_row=portfolio_row,
                )
            )
        experiments.sort(
            key=lambda item: (
                item["gate"]["status"] != "PASS",
                -float(item["portfolio"]["roi"] or 0.0),
                float(item["portfolio"]["max_drawdown_pct"] or 0.0),
            )
        )
        return {
            "quality_report_version": QUALITY_REPORT_VERSION,
            "gate_mode": QUALITY_GATE_MODE,
            "canonical_event_id": str(canonical_event_id),
            "policy": {
                "min_settled_maps": self._policy.min_settled_maps,
                "min_settled_bets": self._policy.min_settled_bets,
                "min_prediction_samples": self._policy.min_prediction_samples,
                "min_clv_samples": self._policy.min_clv_samples,
                "min_market_comparison_samples": self._policy.min_market_comparison_samples,
                "min_roi": self._policy.min_roi,
                "min_average_clv": self._policy.min_average_clv,
                "min_brier_improvement_vs_market": (self._policy.min_brier_improvement_vs_market),
                "max_drawdown_pct": self._policy.max_drawdown_pct,
            },
            "experiments": experiments,
        }

    async def _experiment_report(
        self,
        session: AsyncSession,
        *,
        canonical_event_id: UUID,
        portfolio_row: dict[str, Any],
    ) -> dict[str, Any]:
        account_id = UUID(portfolio_row["account_id"])
        identity = portfolio_row["experiment"]
        position_pairs = list(
            (
                await session.execute(
                    select(TournamentPortfolioPositionRecord, AiDecisionRecord)
                    .join(
                        AiDecisionRecord,
                        AiDecisionRecord.id == TournamentPortfolioPositionRecord.ai_decision_id,
                    )
                    .where(TournamentPortfolioPositionRecord.portfolio_account_id == account_id)
                    .order_by(TournamentPortfolioPositionRecord.opened_at)
                )
            ).all()
        )
        stake_ratios = [
            float(position.stake) / float(position.cash_before)
            for position, _ in position_pairs
            if float(position.cash_before) > 0 and position.status != "REJECTED"
        ]
        settled_positions = [
            position for position, _ in position_pairs if position.status in {"WON", "LOST"}
        ]
        losing_streak = _longest_losing_streak(settled_positions)

        decision_rows = list(
            (
                await session.execute(
                    select(
                        AiDecisionRecord,
                        DecisionSnapshotRecord,
                        CanonicalSeries,
                        MapResultRecord,
                        DecisionEvaluationRecord,
                    )
                    .join(
                        DecisionSnapshotRecord,
                        DecisionSnapshotRecord.id == AiDecisionRecord.snapshot_id,
                    )
                    .join(
                        CanonicalMap,
                        CanonicalMap.id == DecisionSnapshotRecord.canonical_map_id,
                    )
                    .join(CanonicalSeries, CanonicalSeries.id == CanonicalMap.series_id)
                    .outerjoin(
                        MapResultRecord,
                        MapResultRecord.canonical_map_id == CanonicalMap.id,
                    )
                    .outerjoin(
                        DecisionEvaluationRecord,
                        DecisionEvaluationRecord.ai_decision_id == AiDecisionRecord.id,
                    )
                    .where(
                        CanonicalSeries.event_id == canonical_event_id,
                        AiDecisionRecord.provider == identity["provider"],
                        AiDecisionRecord.model == identity["model"],
                        AiDecisionRecord.prompt_version == identity["prompt_version"],
                        AiDecisionRecord.decision_policy_version
                        == identity["decision_policy_version"],
                        AiDecisionRecord.ai_view_version == identity["ai_view_version"],
                        AiDecisionRecord.execution_config_version
                        == identity["execution_config_version"],
                        AiDecisionRecord.parse_status == "SUCCESS",
                        AiDecisionRecord.normalized_response.is_not(None),
                    )
                    .order_by(DecisionSnapshotRecord.decision_at)
                )
            ).all()
        )

        action_counts: Counter[str] = Counter()
        settled_maps: set[UUID] = set()
        decision_level_briers: list[float] = []
        decision_level_losses: list[float] = []
        decision_level_clvs: list[float] = []
        map_forecasts: dict[UUID, dict[str, float | None]] = {}
        first_settled_position_by_map: dict[UUID, UUID] = {}
        for position, _ in position_pairs:
            if (
                position.status in {"WON", "LOST"}
                and position.canonical_map_id not in first_settled_position_by_map
            ):
                first_settled_position_by_map[position.canonical_map_id] = position.ai_decision_id

        map_clvs: list[float] = []
        for decision_record, snapshot, series, result, evaluation in decision_rows:
            try:
                decision = AiDecision.model_validate(decision_record.normalized_response)
            except ValidationError:
                continue
            action_counts[decision.action] += 1
            if (
                result is None
                or result.provider_conflict
                or result.winner_team_id is None
                or result.winner_team_id not in {series.team_a_id, series.team_b_id}
                or snapshot.canonical_map_id is None
            ):
                continue
            map_id = snapshot.canonical_map_id
            settled_maps.add(map_id)
            if evaluation is not None:
                if evaluation.brier_score is not None:
                    decision_level_briers.append(float(evaluation.brier_score))
                if evaluation.log_loss is not None:
                    decision_level_losses.append(float(evaluation.log_loss))
                if evaluation.clv is not None:
                    decision_level_clvs.append(float(evaluation.clv))
                    if first_settled_position_by_map.get(map_id) == decision_record.id:
                        map_clvs.append(float(evaluation.clv))
            team_a_won = result.winner_team_id == series.team_a_id
            market_probability = _market_probability_a(
                snapshot.canonical_payload,
                team_a_id=series.team_a_id,
                team_b_id=series.team_b_id,
            )
            market_brier = brier_score(market_probability, team_a_won)
            market_loss = log_loss(market_probability, team_a_won)
            ai_brier = (
                float(evaluation.brier_score)
                if evaluation is not None and evaluation.brier_score is not None
                else None
            )
            ai_log_loss = (
                float(evaluation.log_loss)
                if evaluation is not None and evaluation.log_loss is not None
                else None
            )
            if map_id not in map_forecasts and ai_brier is not None and ai_log_loss is not None:
                map_forecasts[map_id] = {
                    "ai_brier": ai_brier,
                    "ai_log_loss": ai_log_loss,
                    "market_brier": float(market_brier) if market_brier is not None else None,
                    "market_log_loss": (float(market_loss) if market_loss is not None else None),
                }

        map_briers = [
            float(row["ai_brier"]) for row in map_forecasts.values() if row["ai_brier"] is not None
        ]
        map_losses = [
            float(row["ai_log_loss"])
            for row in map_forecasts.values()
            if row["ai_log_loss"] is not None
        ]
        comparable = [
            row
            for row in map_forecasts.values()
            if row["ai_brier"] is not None
            and row["ai_log_loss"] is not None
            and row["market_brier"] is not None
            and row["market_log_loss"] is not None
        ]
        comparable_ai_briers = [float(row["ai_brier"]) for row in comparable]
        comparable_ai_losses = [float(row["ai_log_loss"]) for row in comparable]
        market_briers = [float(row["market_brier"]) for row in comparable]
        market_losses = [float(row["market_log_loss"]) for row in comparable]

        avg_brier = _average(map_briers)
        avg_loss = _average(map_losses)
        avg_clv = _average(map_clvs)
        ai_brier_comparable = _average(comparable_ai_briers)
        ai_loss_comparable = _average(comparable_ai_losses)
        market_brier = _average(market_briers)
        market_loss = _average(market_losses)
        brier_improvement = _difference(market_brier, ai_brier_comparable)
        log_loss_improvement = _difference(market_loss, ai_loss_comparable)

        risk_adjusted_return = None
        if portfolio_row["max_drawdown_pct"] and portfolio_row["max_drawdown_pct"] > 0:
            risk_adjusted_return = portfolio_row["roi"] / portfolio_row["max_drawdown_pct"]

        metrics = {
            "sample_policy": {
                "prediction": "FIRST_EVALUABLE_FORECAST_PER_MAP",
                "clv": "FIRST_SETTLED_POSITION_PER_MAP",
                "portfolio": "ALL_EXECUTED_POSITIONS",
            },
            "settled_maps": len(settled_maps),
            "successful_decisions": len(decision_rows),
            "action_counts": dict(sorted(action_counts.items())),
            "prediction_sample_count": len(map_briers),
            "average_brier_score": avg_brier,
            "average_log_loss": avg_loss,
            "average_clv": avg_clv,
            "clv_sample_count": len(map_clvs),
            "market_comparison": {
                "sample_count": len(comparable),
                "market_average_brier_score": market_brier,
                "ai_average_brier_score": ai_brier_comparable,
                "brier_improvement_vs_market": brier_improvement,
                "market_average_log_loss": market_loss,
                "ai_average_log_loss": ai_loss_comparable,
                "log_loss_improvement_vs_market": log_loss_improvement,
            },
            "decision_level": {
                "prediction_sample_count": len(decision_level_briers),
                "average_brier_score": _average(decision_level_briers),
                "average_log_loss": _average(decision_level_losses),
                "average_clv": _average(decision_level_clvs),
                "clv_sample_count": len(decision_level_clvs),
            },
            "average_stake_pct_of_available_cash": _average(stake_ratios),
            "largest_stake_pct_of_available_cash": max(stake_ratios, default=None),
            "longest_losing_streak": losing_streak,
            "risk_adjusted_return_over_max_drawdown": risk_adjusted_return,
        }
        gate = self._gate(portfolio_row, metrics)
        curve = await self._equity_curve(session, account_id=account_id)
        execution_latency = await self._latency.build_experiment_report(
            session,
            account_id=account_id,
        )
        return {
            "experiment": identity,
            "portfolio": portfolio_row,
            "quality": metrics,
            "execution_latency": execution_latency,
            "gate": gate,
            "equity_curve": curve,
        }

    def _gate(
        self,
        portfolio: dict[str, Any],
        quality: dict[str, Any],
    ) -> dict[str, Any]:
        sample_failures = []
        if quality["settled_maps"] < self._policy.min_settled_maps:
            sample_failures.append("MIN_SETTLED_MAPS")
        if portfolio["bet_count"] < self._policy.min_settled_bets:
            sample_failures.append("MIN_SETTLED_BETS")
        if quality["prediction_sample_count"] < self._policy.min_prediction_samples:
            sample_failures.append("MIN_PREDICTION_SAMPLES")
        if quality["clv_sample_count"] < self._policy.min_clv_samples:
            sample_failures.append("MIN_CLV_SAMPLES")
        if (
            quality["market_comparison"]["sample_count"]
            < self._policy.min_market_comparison_samples
        ):
            sample_failures.append("MIN_MARKET_COMPARISON_SAMPLES")
        if sample_failures:
            return {
                "mode": QUALITY_GATE_MODE,
                "status": "INSUFFICIENT_SAMPLE",
                "failures": sample_failures,
            }

        failures = []
        if portfolio["roi"] is None or portfolio["roi"] < self._policy.min_roi:
            failures.append("ROI")
        if quality["average_clv"] is None or quality["average_clv"] < self._policy.min_average_clv:
            failures.append("CLV")
        brier_improvement = quality["market_comparison"]["brier_improvement_vs_market"]
        if (
            brier_improvement is None
            or brier_improvement < self._policy.min_brier_improvement_vs_market
        ):
            failures.append("BRIER_VS_MARKET")
        if portfolio["max_drawdown_pct"] > self._policy.max_drawdown_pct:
            failures.append("MAX_DRAWDOWN")
        if portfolio["status"] == "BANKRUPT":
            failures.append("BANKRUPTCY")
        return {
            "mode": QUALITY_GATE_MODE,
            "status": "PASS" if not failures else "FAIL",
            "failures": failures,
        }

    async def _equity_curve(
        self,
        session: AsyncSession,
        *,
        account_id: UUID,
    ) -> list[dict[str, Any]]:
        entries = list(
            (
                await session.scalars(
                    select(TournamentPortfolioLedgerRecord)
                    .where(TournamentPortfolioLedgerRecord.portfolio_account_id == account_id)
                    .order_by(TournamentPortfolioLedgerRecord.occurred_at)
                )
            ).all()
        )
        grouped: dict[Any, list[TournamentPortfolioLedgerRecord]] = {}
        for entry in entries:
            grouped.setdefault(entry.occurred_at, []).append(entry)

        cash = Decimal("0")
        locked = Decimal("0")
        curve: list[dict[str, Any]] = []
        for occurred_at, batch in sorted(grouped.items(), key=lambda item: item[0]):
            cash += sum((Decimal(item.cash_delta) for item in batch), Decimal("0"))
            locked += sum((Decimal(item.locked_delta) for item in batch), Decimal("0"))
            realized_delta = sum(
                (Decimal(item.realized_pnl_delta) for item in batch),
                Decimal("0"),
            )
            visible_types = [item.entry_type for item in batch if item.entry_type != "BET_PLACED"]
            if not visible_types:
                continue
            entry_type = visible_types[0] if len(set(visible_types)) == 1 else "SETTLEMENT_BATCH"
            curve.append(
                {
                    "occurred_at": occurred_at,
                    "entry_type": entry_type,
                    "equity": float(cash + locked),
                    "cash": float(cash),
                    "locked": float(locked),
                    "realized_pnl_delta": float(realized_delta),
                }
            )
        return curve


def _market_probability_a(
    payload: dict[str, Any],
    *,
    team_a_id: UUID,
    team_b_id: UUID,
) -> float | None:
    market = payload.get("market")
    if not isinstance(market, dict):
        return None
    observations = market.get("observations")
    if not isinstance(observations, list):
        return None
    odds_a = None
    odds_b = None
    for item in observations:
        if not isinstance(item, dict):
            continue
        try:
            price = float(item.get("price"))
        except TypeError, ValueError:
            continue
        if price <= 1:
            continue
        selection = item.get("selection_team_id")
        if selection is not None and str(selection) == str(team_a_id):
            odds_a = price
        elif selection is not None and str(selection) == str(team_b_id):
            odds_b = price
    if odds_a is None or odds_b is None:
        return None
    implied_a = 1.0 / odds_a
    implied_b = 1.0 / odds_b
    total = implied_a + implied_b
    return implied_a / total if total > 0 else None


def _longest_losing_streak(
    positions: list[TournamentPortfolioPositionRecord],
) -> int:
    longest = 0
    current = 0
    for position in positions:
        if position.status == "LOST":
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def _average(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _difference(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return left - right
