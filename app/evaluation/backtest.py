"""Historical decision-level backtesting for settled AI experiments."""

from collections import Counter
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.decision import AiDecision
from app.evaluation.metrics import brier_score, log_loss
from app.models import (
    AiDecisionRecord,
    DecisionFutureOdds,
    DecisionSnapshotRecord,
    MapResultRecord,
)

BACKTEST_VERSION = "decision-backtest-v1"


class BacktestService:
    async def build_report(
        self,
        session: AsyncSession,
        *,
        provider: str | None = None,
        model: str | None = None,
        prompt_version: str | None = None,
        ai_view_version: str | None = None,
        calibration_bins: int = 10,
        include_snapshot_payload: bool = False,
    ) -> dict[str, Any]:
        """Build a settled, experiment-isolated paper backtest report."""
        _validate_bin_count(calibration_bins)
        query = select(AiDecisionRecord).where(
            AiDecisionRecord.parse_status == "SUCCESS",
            AiDecisionRecord.normalized_response.is_not(None),
        )
        if provider is not None:
            query = query.where(AiDecisionRecord.provider == provider)
        if model is not None:
            query = query.where(AiDecisionRecord.model == model)
        if prompt_version is not None:
            query = query.where(AiDecisionRecord.prompt_version == prompt_version)
        if ai_view_version is not None:
            query = query.where(AiDecisionRecord.ai_view_version == ai_view_version)
        decisions = list(
            (await session.scalars(query.order_by(AiDecisionRecord.request_started_at))).all()
        )
        if not decisions:
            return _report([], calibration_bins, include_snapshot_payload)

        snapshot_ids = list({record.snapshot_id for record in decisions})
        snapshots = list(
            (
                await session.scalars(
                    select(DecisionSnapshotRecord).where(
                        DecisionSnapshotRecord.id.in_(snapshot_ids)
                    )
                )
            ).all()
        )
        snapshots_by_id = {snapshot.id: snapshot for snapshot in snapshots}
        map_ids = list(
            {
                snapshot.canonical_map_id
                for snapshot in snapshots
                if snapshot.canonical_map_id is not None
            }
        )
        results = (
            list(
                (
                    await session.scalars(
                        select(MapResultRecord).where(MapResultRecord.canonical_map_id.in_(map_ids))
                    )
                ).all()
            )
            if map_ids
            else []
        )
        results_by_map_id = {result.canonical_map_id: result for result in results}
        closing_rows = list(
            (
                await session.scalars(
                    select(DecisionFutureOdds)
                    .where(
                        DecisionFutureOdds.decision_snapshot_id.in_(snapshot_ids),
                        DecisionFutureOdds.capture_type == "CLOSING",
                        DecisionFutureOdds.status == "CAPTURED",
                    )
                    .order_by(DecisionFutureOdds.due_at.desc())
                )
            ).all()
        )
        closing_by_snapshot: dict[Any, DecisionFutureOdds] = {}
        for closing in closing_rows:
            snapshot = snapshots_by_id.get(closing.decision_snapshot_id)
            if snapshot is None or not _same_market(snapshot.canonical_payload, closing):
                continue
            closing_by_snapshot.setdefault(closing.decision_snapshot_id, closing)

        rows: list[dict[str, Any]] = []
        for record in decisions:
            snapshot = snapshots_by_id.get(record.snapshot_id)
            if snapshot is None or snapshot.canonical_map_id is None:
                continue
            result = results_by_map_id.get(snapshot.canonical_map_id)
            if (
                result is None
                or result.provider_conflict
                or result.winner_team_id is None
            ):
                continue
            actual_winner = _actual_winner(snapshot.canonical_payload, result.winner_team_id)
            if actual_winner is None:
                continue

            decision = AiDecision.model_validate(record.normalized_response)
            odds_a, odds_b, price_mapping = _initial_prices(snapshot.canonical_payload)
            selected_odds = odds_a if decision.action == "BUY_A" else odds_b
            unit_return = _unit_return(decision.action, selected_odds, actual_winner)
            closing = closing_by_snapshot.get(snapshot.id)
            closing_a = float(closing.odds_a) if closing and closing.odds_a is not None else None
            closing_b = float(closing.odds_b) if closing and closing.odds_b is not None else None
            clv = _clv(decision.action, odds_a, odds_b, closing_a, closing_b)
            team_a_won = actual_winner == "A"
            row: dict[str, Any] = {
                "ai_decision_id": str(record.id),
                "snapshot_id": str(snapshot.id),
                "canonical_map_id": str(snapshot.canonical_map_id),
                "snapshot_hash": snapshot.snapshot_hash,
                "ai_input_hash": record.ai_input_hash,
                "decision_at": snapshot.decision_at.isoformat(),
                "mode": snapshot.mode,
                "experiment": _experiment_identity(record),
                "action": decision.action,
                "confidence": decision.confidence,
                "fair_probability_a": decision.fair_probability_a,
                "market_odds_a": odds_a,
                "market_odds_b": odds_b,
                "market_price_mapping": price_mapping,
                "actual_winner": actual_winner,
                "result_correct": _result_correct(decision.action, actual_winner),
                "unit_return": unit_return,
                "brier_score": brier_score(decision.fair_probability_a, team_a_won),
                "log_loss": log_loss(decision.fair_probability_a, team_a_won),
                "closing_odds_a": closing_a,
                "closing_odds_b": closing_b,
                "clv": clv,
            }
            if include_snapshot_payload:
                row["snapshot_payload"] = snapshot.canonical_payload
            rows.append(row)

        return _report(rows, calibration_bins, include_snapshot_payload)


def summarize_backtest_rows(
    rows: list[dict[str, Any]], *, calibration_bins: int = 10
) -> list[dict[str, Any]]:
    """Aggregate settled rows while keeping experiment versions isolated."""
    _validate_bin_count(calibration_bins)
    grouped: dict[tuple[str, str, str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        experiment = row.get("experiment")
        if not isinstance(experiment, dict):
            continue
        key = (
            str(experiment.get("provider")),
            str(experiment.get("model")),
            str(experiment.get("prompt_version")),
            str(experiment.get("decision_policy_version")),
            str(experiment.get("ai_view_version")),
        )
        grouped.setdefault(key, []).append(row)

    summaries = []
    for key, experiment_rows in sorted(grouped.items()):
        bet_rows = [row for row in experiment_rows if row.get("unit_return") is not None]
        returns = [float(row["unit_return"]) for row in bet_rows]
        wins = sum(row.get("result_correct") is True for row in bet_rows)
        action_counts = Counter(str(row.get("action")) for row in experiment_rows)
        briers = _numbers(row.get("brier_score") for row in experiment_rows)
        losses = _numbers(row.get("log_loss") for row in experiment_rows)
        clvs = _numbers(row.get("clv") for row in bet_rows)
        calibration = _calibration(experiment_rows, calibration_bins)
        summaries.append(
            {
                "experiment": {
                    "provider": key[0],
                    "model": key[1],
                    "prompt_version": key[2],
                    "decision_policy_version": key[3],
                    "ai_view_version": key[4],
                },
                "settled_decisions": len(experiment_rows),
                "unique_maps": len({row.get("canonical_map_id") for row in experiment_rows}),
                "action_counts": dict(sorted(action_counts.items())),
                "bet_count": len(bet_rows),
                "wins": wins,
                "losses": len(bet_rows) - wins,
                "hit_rate": _ratio(wins, len(bet_rows)),
                "unit_profit": round(sum(returns), 6),
                "decision_level_roi": _ratio(sum(returns), len(bet_rows)),
                "average_brier_score": _average(briers),
                "average_log_loss": _average(losses),
                "average_clv": _average(clvs),
                "clv_sample_count": len(clvs),
                "calibration": calibration,
            }
        )
    return summaries


def _report(
    rows: list[dict[str, Any]], calibration_bins: int, include_snapshot_payload: bool
) -> dict[str, Any]:
    return {
        "backtest_version": BACKTEST_VERSION,
        "assumptions": {
            "stake_policy": "1 unit per BUY decision",
            "return_price": "decimal odds frozen in the immutable decision snapshot",
            "repeated_snapshots": "each BUY decision is a separate paper bet",
            "costs_and_limits": "fees, slippage, rejection, liquidity and stake limits are ignored",
            "settlement": "only non-conflicted maps with a resolved winner are included",
            "input_audit": (
                "ai_input_hash identifies exact provider input bytes; snapshot_payload is the immutable "
                "source snapshot and can be included explicitly, but historical transformed inputs are "
                "not reconstructed under newer ai-view code"
            ),
        },
        "calibration_bins": calibration_bins,
        "snapshot_payload_included": include_snapshot_payload,
        "settled_row_count": len(rows),
        "experiments": summarize_backtest_rows(rows, calibration_bins=calibration_bins),
        "rows": rows,
    }


def _experiment_identity(record: AiDecisionRecord) -> dict[str, str]:
    return {
        "provider": record.provider,
        "model": record.model,
        "model_version": record.model_version,
        "prompt_version": record.prompt_version,
        "decision_policy_version": record.decision_policy_version,
        "ai_view_version": record.ai_view_version,
    }


def _actual_winner(payload: dict[str, Any], winner_team_id: Any) -> str | None:
    identity = _dict(payload.get("identity"))
    team_a_id = _dict(identity.get("team_a")).get("id")
    team_b_id = _dict(identity.get("team_b")).get("id")
    winner = str(winner_team_id)
    if team_a_id is not None and winner == str(team_a_id):
        return "A"
    if team_b_id is not None and winner == str(team_b_id):
        return "B"
    return None


def _initial_prices(payload: dict[str, Any]) -> tuple[float | None, float | None, str]:
    identity = _dict(payload.get("identity"))
    team_a_id = _dict(identity.get("team_a")).get("id")
    team_b_id = _dict(identity.get("team_b")).get("id")
    observations = _dict(payload.get("market")).get("observations") or []
    odds_a = None
    odds_b = None
    legacy_prices = []
    for observation in observations:
        if not isinstance(observation, dict):
            continue
        price = _number(observation.get("price"))
        if price is None:
            continue
        legacy_prices.append(price)
        selection_team_id = observation.get("selection_team_id")
        if team_a_id is not None and str(selection_team_id) == str(team_a_id):
            odds_a = price
        elif team_b_id is not None and str(selection_team_id) == str(team_b_id):
            odds_b = price
    if odds_a is not None and odds_b is not None:
        return odds_a, odds_b, "TEAM_ID"
    if len(legacy_prices) >= 2:
        return legacy_prices[0], legacy_prices[1], "LEGACY_OBSERVATION_ORDER"
    return odds_a, odds_b, "INCOMPLETE"


def _same_market(payload: dict[str, Any], closing: DecisionFutureOdds) -> bool:
    market = _dict(payload.get("market"))
    return (
        market.get("market_type") == closing.market_type
        and market.get("match_stage") == closing.match_stage
    )


def _unit_return(action: str, selected_odds: float | None, actual_winner: str) -> float | None:
    if action not in {"BUY_A", "BUY_B"} or selected_odds is None:
        return None
    won = (action == "BUY_A" and actual_winner == "A") or (
        action == "BUY_B" and actual_winner == "B"
    )
    return round(selected_odds - 1.0, 6) if won else -1.0


def _result_correct(action: str, actual_winner: str) -> bool | None:
    if action == "BUY_A":
        return actual_winner == "A"
    if action == "BUY_B":
        return actual_winner == "B"
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


def _calibration(rows: list[dict[str, Any]], bin_count: int) -> dict[str, Any]:
    samples = [
        (float(row["fair_probability_a"]), 1.0 if row.get("actual_winner") == "A" else 0.0)
        for row in rows
        if _number(row.get("fair_probability_a")) is not None
    ]
    buckets: list[list[tuple[float, float]]] = [[] for _ in range(bin_count)]
    for probability, outcome in samples:
        probability = min(max(probability, 0.0), 1.0)
        index = min(bin_count - 1, int(probability * bin_count))
        buckets[index].append((probability, outcome))

    output_bins = []
    weighted_error = 0.0
    for index, bucket in enumerate(buckets):
        if not bucket:
            continue
        mean_probability = sum(item[0] for item in bucket) / len(bucket)
        win_rate = sum(item[1] for item in bucket) / len(bucket)
        absolute_gap = abs(win_rate - mean_probability)
        weighted_error += len(bucket) * absolute_gap
        output_bins.append(
            {
                "lower": round(index / bin_count, 3),
                "upper": round((index + 1) / bin_count, 3),
                "count": len(bucket),
                "mean_predicted_a": round(mean_probability, 6),
                "actual_a_win_rate": round(win_rate, 6),
                "calibration_gap": round(win_rate - mean_probability, 6),
            }
        )
    return {
        "sample_count": len(samples),
        "expected_calibration_error": (
            round(weighted_error / len(samples), 6) if samples else None
        ),
        "bins": output_bins,
    }


def _validate_bin_count(bin_count: int) -> None:
    if not 2 <= bin_count <= 20:
        raise ValueError("calibration_bins must be between 2 and 20")


def _ratio(numerator: float, denominator: int) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


def _average(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 6) if values else None


def _numbers(values: Any) -> list[float]:
    return [number for value in values if (number := _number(value)) is not None]


def _number(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
