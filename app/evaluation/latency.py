from __future__ import annotations

from collections import defaultdict
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.decision import AiDecision, target_probability
from app.evaluation.portfolio_models import TournamentPortfolioPositionRecord
from app.models import AiDecisionRecord, DecisionFutureOdds
from app.time import ensure_utc


class LatencyExecutionService:
    """Describe whether a BUY signal still has paper edge at future market captures.

    Existing TIME_HORIZON captures are scheduled from the immutable snapshot.
    Because provider inference itself takes time, the report also exposes the
    actual seconds between AI response and the captured market observation.
    This is paper execution evidence, not a claim that a bookmaker accepted a bet.
    """

    async def build_experiment_report(
        self,
        session: AsyncSession,
        *,
        account_id: UUID,
    ) -> dict[str, Any]:
        pairs = list(
            (
                await session.execute(
                    select(TournamentPortfolioPositionRecord, AiDecisionRecord)
                    .join(
                        AiDecisionRecord,
                        AiDecisionRecord.id == TournamentPortfolioPositionRecord.ai_decision_id,
                    )
                    .where(
                        TournamentPortfolioPositionRecord.portfolio_account_id == account_id,
                        TournamentPortfolioPositionRecord.status.in_(("WON", "LOST")),
                    )
                    .order_by(
                        TournamentPortfolioPositionRecord.opened_at,
                        TournamentPortfolioPositionRecord.id,
                    )
                )
            ).all()
        )
        first_by_map: dict[UUID, tuple[TournamentPortfolioPositionRecord, AiDecisionRecord]] = {}
        for position, decision_record in pairs:
            first_by_map.setdefault(position.canonical_map_id, (position, decision_record))
        if not first_by_map:
            return _empty_report()

        snapshot_ids = [record.snapshot_id for _, record in first_by_map.values()]
        captures = list(
            (
                await session.scalars(
                    select(DecisionFutureOdds)
                    .where(
                        DecisionFutureOdds.decision_snapshot_id.in_(snapshot_ids),
                        DecisionFutureOdds.capture_type == "TIME_HORIZON",
                        DecisionFutureOdds.status == "CAPTURED",
                        DecisionFutureOdds.horizon_seconds.is_not(None),
                    )
                    .order_by(
                        DecisionFutureOdds.horizon_seconds,
                        DecisionFutureOdds.observed_at,
                    )
                )
            ).all()
        )
        by_snapshot: dict[UUID, list[DecisionFutureOdds]] = defaultdict(list)
        for capture in captures:
            by_snapshot[capture.decision_snapshot_id].append(capture)

        horizon_samples: dict[int, list[dict[str, float | bool]]] = defaultdict(list)
        pre_response_capture_count = 0
        invalid_pair_capture_count = 0
        for position, record in first_by_map.values():
            if position.odds is None or record.normalized_response is None:
                continue
            try:
                decision = AiDecision.model_validate(record.normalized_response)
            except ValidationError:
                continue
            probability = target_probability(decision.action, decision.fair_probability_a)
            if probability is None:
                continue
            initial_odds = float(position.odds)
            if initial_odds <= 1:
                continue
            for capture in by_snapshot.get(record.snapshot_id, ()):
                horizon = capture.horizon_seconds
                if horizon is None:
                    continue
                pair_quality = (
                    capture.pair_quality if isinstance(capture.pair_quality, dict) else {}
                )
                if pair_quality.get("eligible") is not True:
                    invalid_pair_capture_count += 1
                    continue
                if (
                    record.response_received_at is not None
                    and capture.observed_at is not None
                    and ensure_utc(capture.observed_at) < ensure_utc(record.response_received_at)
                ):
                    pre_response_capture_count += 1
                    continue
                future_odds = _selected_future_odds(capture, action=position.action)
                if future_odds is None or future_odds <= 1:
                    continue
                edge = probability - (1.0 / future_odds)
                sample: dict[str, float | bool] = {
                    "odds_slippage_pct": future_odds / initial_odds - 1.0,
                    "model_edge_vs_break_even": edge,
                    "actionable": edge > 0,
                }
                if record.response_received_at is not None and capture.observed_at is not None:
                    sample["observed_after_ai_seconds"] = (
                        ensure_utc(capture.observed_at) - ensure_utc(record.response_received_at)
                    ).total_seconds()
                horizon_samples[horizon].append(sample)

        return {
            "source": "DECISION_FUTURE_ODDS_TIME_HORIZON",
            "position_policy": "FIRST_SETTLED_POSITION_PER_MAP",
            "interpretation": "PAPER_MARKET_OBSERVATION_NOT_EXECUTION_CONFIRMATION",
            "pre_response_capture_count": pre_response_capture_count,
            "invalid_pair_capture_count": invalid_pair_capture_count,
            "horizons": {
                str(horizon): _summarize_horizon(samples)
                for horizon, samples in sorted(horizon_samples.items())
            },
        }


def _selected_future_odds(capture: DecisionFutureOdds, *, action: str) -> float | None:
    raw = capture.odds_a if action == "BUY_A" else capture.odds_b
    return float(raw) if raw is not None else None


def _summarize_horizon(samples: list[dict[str, float | bool]]) -> dict[str, Any]:
    edges = [float(item["model_edge_vs_break_even"]) for item in samples]
    slippage = [float(item["odds_slippage_pct"]) for item in samples]
    delays = [
        float(item["observed_after_ai_seconds"])
        for item in samples
        if "observed_after_ai_seconds" in item
    ]
    actionable = sum(bool(item["actionable"]) for item in samples)
    return {
        "sample_count": len(samples),
        "actionable_count": actionable,
        "actionable_rate": actionable / len(samples) if samples else None,
        "average_model_edge_vs_break_even": _average(edges),
        "average_odds_slippage_pct": _average(slippage),
        "average_observed_after_ai_seconds": _average(delays),
    }


def _empty_report() -> dict[str, Any]:
    return {
        "source": "DECISION_FUTURE_ODDS_TIME_HORIZON",
        "position_policy": "FIRST_SETTLED_POSITION_PER_MAP",
        "interpretation": "PAPER_MARKET_OBSERVATION_NOT_EXECUTION_CONFIRMATION",
        "pre_response_capture_count": 0,
        "invalid_pair_capture_count": 0,
        "horizons": {},
    }


def _average(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None
