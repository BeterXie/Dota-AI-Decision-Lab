from datetime import UTC, datetime
from math import log
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.decision import AiDecision
from app.models import (
    AiDecisionRecord,
    DecisionEvaluationRecord,
    DecisionFutureOdds,
    DecisionSnapshotRecord,
    MapResultRecord,
)

METRICS_VERSION = "decision-evaluation-v1"


class EvaluationService:
    async def evaluate_snapshot(self, session: AsyncSession, *, snapshot_id: UUID) -> int:
        snapshot = await session.get(DecisionSnapshotRecord, snapshot_id)
        if snapshot is None or snapshot.canonical_map_id is None:
            raise ValueError("snapshot has no canonical map")
        result = await session.scalar(
            select(MapResultRecord).where(
                MapResultRecord.canonical_map_id == snapshot.canonical_map_id
            )
        )
        if result is None or result.provider_conflict or result.winner_team_id is None:
            return 0
        team_a_id = snapshot.canonical_payload.get("identity", {}).get("team_a", {}).get("id")
        if not isinstance(team_a_id, str):
            return 0
        team_a_won = str(result.winner_team_id) == team_a_id
        decisions = list(
            (
                await session.scalars(
                    select(AiDecisionRecord).where(
                        AiDecisionRecord.snapshot_id == snapshot_id,
                        AiDecisionRecord.parse_status == "SUCCESS",
                        AiDecisionRecord.normalized_response.is_not(None),
                    )
                )
            ).all()
        )
        future = list(
            (
                await session.scalars(
                    select(DecisionFutureOdds)
                    .where(
                        DecisionFutureOdds.decision_snapshot_id == snapshot_id,
                        DecisionFutureOdds.status == "CAPTURED",
                    )
                    .order_by(DecisionFutureOdds.horizon_seconds)
                )
            ).all()
        )
        created = 0
        for record in decisions:
            existing = await session.scalar(
                select(DecisionEvaluationRecord.id).where(
                    DecisionEvaluationRecord.ai_decision_id == record.id
                )
            )
            if existing is not None:
                continue
            decision = AiDecision.model_validate(record.normalized_response)
            initial_a, initial_b = _initial_prices(snapshot)
            closing = next((item for item in future if item.horizon_seconds == -1), None)
            first_future = next((item for item in future if item.horizon_seconds > 0), None)
            session.add(
                DecisionEvaluationRecord(
                    ai_decision_id=record.id,
                    result_correct=_result_correct(decision.action, team_a_won),
                    brier_score=brier_score(decision.fair_probability_a, team_a_won),
                    log_loss=log_loss(decision.fair_probability_a, team_a_won),
                    clv=_clv(
                        decision.action,
                        initial_a,
                        initial_b,
                        float(closing.odds_a) if closing and closing.odds_a else None,
                        float(closing.odds_b) if closing and closing.odds_b else None,
                    ),
                    future_odds_direction=_future_direction(
                        decision.action,
                        initial_a,
                        initial_b,
                        (
                            float(first_future.odds_a)
                            if first_future and first_future.odds_a
                            else None
                        ),
                        (
                            float(first_future.odds_b)
                            if first_future and first_future.odds_b
                            else None
                        ),
                    ),
                    evaluated_at=datetime.now(UTC),
                    metrics_version=METRICS_VERSION,
                )
            )
            created += 1
        return created


def brier_score(probability_a: float | None, team_a_won: bool) -> float | None:
    if probability_a is None:
        return None
    return (probability_a - float(team_a_won)) ** 2


def log_loss(probability_a: float | None, team_a_won: bool) -> float | None:
    if probability_a is None:
        return None
    probability = min(max(probability_a, 1e-12), 1.0 - 1e-12)
    return -(log(probability) if team_a_won else log(1.0 - probability))


def _result_correct(action: str, team_a_won: bool) -> bool | None:
    if action == "BUY_A":
        return team_a_won
    if action == "BUY_B":
        return not team_a_won
    return None


def _clv(
    action: str,
    initial_a: float | None,
    initial_b: float | None,
    closing_a: float | None,
    closing_b: float | None,
) -> float | None:
    if action == "BUY_A" and initial_a is not None and closing_a is not None:
        return initial_a / closing_a - 1.0
    if action == "BUY_B" and initial_b is not None and closing_b is not None:
        return initial_b / closing_b - 1.0
    return None


def _future_direction(
    action: str,
    initial_a: float | None,
    initial_b: float | None,
    future_a: float | None,
    future_b: float | None,
) -> str | None:
    if action == "BUY_A" and initial_a is not None and future_a is not None:
        return (
            "FAVORABLE"
            if future_a < initial_a
            else "UNFAVORABLE"
            if future_a > initial_a
            else "FLAT"
        )
    if action == "BUY_B" and initial_b is not None and future_b is not None:
        return (
            "FAVORABLE"
            if future_b < initial_b
            else "UNFAVORABLE"
            if future_b > initial_b
            else "FLAT"
        )
    return None


def _initial_prices(
    snapshot: DecisionSnapshotRecord,
) -> tuple[float | None, float | None]:
    observations = snapshot.canonical_payload.get("market", {}).get("observations", [])
    prices = [
        float(item["price"])
        for item in observations
        if isinstance(item, dict) and item.get("price") is not None
    ]
    return (
        prices[0] if len(prices) > 0 else None,
        prices[1] if len(prices) > 1 else None,
    )
