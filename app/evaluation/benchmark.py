from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.decision import AiDecision
from app.domain.experiment import AiExperimentKey
from app.evaluation.leaderboard import TournamentLeaderboardService
from app.models import (
    AiDecisionRecord,
    CanonicalMap,
    CanonicalSeries,
    DecisionEvaluationRecord,
    DecisionSnapshotRecord,
    MapResultRecord,
)

BENCHMARK_REPORT_VERSION = "ai-benchmark-v2"
BASELINE_ID = "production-baseline-v1"
BASELINE_FROZEN_AT_COMMIT = "81698ca175a75dfb08285c3725c98835f616a843"
BASELINE_PROMPT_VERSION = "decision-analyst-v5.1-output"
BASELINE_DECISION_POLICY_VERSION = "shadow-tournament-portfolio-v3"
BASELINE_AI_VIEW_VERSION = "ai-view-v6"
CALIBRATION_POLICY_VERSION = "ece-equal-width-10-v1"
CALIBRATION_BIN_COUNT = 10

BASELINE_MODELS_BY_PROVIDER: dict[str, str] = {
    "openai": "gpt-5.6-terra",
    "anthropic": "claude-sonnet-4-6",
    "gemini": "gemini-3.6-flash",
    "deepseek": "deepseek-v4-pro",
}

ExperimentKey = AiExperimentKey


@dataclass(slots=True)
class _ExperimentAccumulator:
    attempts: int = 0
    successful_attempts: int = 0
    model_versions: set[str] = field(default_factory=set)
    parse_statuses: Counter[str] = field(default_factory=Counter)
    action_counts: Counter[str] = field(default_factory=Counter)
    latencies: list[float] = field(default_factory=list)
    forecast_by_map: dict[UUID, tuple[float, bool, float, float, float | None]] = field(
        default_factory=dict
    )
    clv_by_map: dict[UUID, float] = field(default_factory=dict)


class AiBaselineBenchmarkService:
    """Cross-event benchmark for immutable AI experiment identities."""

    def __init__(self, leaderboard: TournamentLeaderboardService | None = None) -> None:
        self._leaderboard = leaderboard or TournamentLeaderboardService()

    async def build_report(self, session: AsyncSession) -> dict[str, Any]:
        leaderboard_report = await self._leaderboard.build_report(session)
        portfolio_by_key = {
            _identity_key_from_dict(row["experiment"]): row
            for row in leaderboard_report.get("experiments", [])
        }

        rows = list(
            (
                await session.execute(
                    select(
                        AiDecisionRecord,
                        DecisionSnapshotRecord,
                        CanonicalMap,
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
                    .order_by(
                        AiDecisionRecord.provider,
                        AiDecisionRecord.model,
                        AiDecisionRecord.prompt_version,
                        AiDecisionRecord.decision_policy_version,
                        AiDecisionRecord.ai_view_version,
                        DecisionSnapshotRecord.decision_at,
                        AiDecisionRecord.id,
                    )
                )
            ).all()
        )

        accumulators: dict[ExperimentKey, _ExperimentAccumulator] = defaultdict(
            _ExperimentAccumulator
        )
        for decision_record, snapshot, canonical_map, series, result, evaluation in rows:
            key = _identity_key(decision_record)
            acc = accumulators[key]
            acc.attempts += 1
            acc.parse_statuses[(decision_record.parse_status or "UNKNOWN").upper()] += 1
            if decision_record.model_version:
                acc.model_versions.add(decision_record.model_version)
            if decision_record.latency_seconds is not None and decision_record.latency_seconds >= 0:
                acc.latencies.append(float(decision_record.latency_seconds))

            if (
                decision_record.parse_status != "SUCCESS"
                or decision_record.normalized_response is None
            ):
                continue
            acc.successful_attempts += 1
            try:
                decision = AiDecision.model_validate(decision_record.normalized_response)
            except ValidationError:
                continue
            acc.action_counts[decision.action] += 1

            map_id = canonical_map.id
            if (
                evaluation is not None
                and evaluation.clv is not None
                and map_id not in acc.clv_by_map
            ):
                acc.clv_by_map[map_id] = float(evaluation.clv)

            if (
                map_id in acc.forecast_by_map
                or decision.fair_probability_a is None
                or evaluation is None
                or evaluation.brier_score is None
                or evaluation.log_loss is None
                or result is None
                or result.provider_conflict
                or result.winner_team_id is None
                or result.winner_team_id not in {series.team_a_id, series.team_b_id}
            ):
                continue
            team_a_won = result.winner_team_id == series.team_a_id
            market_probability = _market_probability_a(
                snapshot.canonical_payload,
                team_a_id=series.team_a_id,
                team_b_id=series.team_b_id,
            )
            acc.forecast_by_map[map_id] = (
                float(decision.fair_probability_a),
                team_a_won,
                float(evaluation.brier_score),
                float(evaluation.log_loss),
                market_probability,
            )

        all_keys = set(accumulators) | set(portfolio_by_key)
        experiments = [
            self._build_experiment_row(
                key,
                accumulators.get(key, _ExperimentAccumulator()),
                portfolio_by_key.get(key),
            )
            for key in all_keys
        ]
        rows_by_key = {_identity_key_from_dict(row["experiment"]): row for row in experiments}
        for row in experiments:
            key = _identity_key_from_dict(row["experiment"])
            baseline_key = _baseline_key_for_provider(key[0], key[5])
            baseline = rows_by_key.get(baseline_key) if baseline_key is not None else None
            row["baseline_reference"] = (
                baseline["experiment"] if baseline is not None and baseline is not row else None
            )
            comparable = bool(
                baseline is not None
                and baseline is not row
                and baseline["execution_config"]["comparison_eligible"]
                and row["execution_config"]["comparison_eligible"]
            )
            row["delta_vs_baseline"] = _comparison_delta(baseline, row) if comparable else None

        experiments.sort(
            key=lambda row: (
                row["baseline_role"] != "BASELINE",
                row["experiment"]["provider"],
                row["experiment"]["model"],
                row["experiment"]["prompt_version"],
                row["experiment"]["ai_view_version"],
            )
        )
        return {
            "benchmark_report_version": BENCHMARK_REPORT_VERSION,
            "baseline_contract": _baseline_contract(),
            "methodology": {
                "forecast_sample": "FIRST_EVALUABLE_FORECAST_PER_MAP",
                "forecast_accuracy": "PREDICT_A_WHEN_FAIR_PROBABILITY_A_GTE_0_5",
                "clv_sample": "FIRST_NON_NULL_CLV_PER_MAP",
                "abstention_actions": ["NO_BUY", "INSUFFICIENT_DATA"],
                "calibration": {
                    "version": CALIBRATION_POLICY_VERSION,
                    "metric": "EXPECTED_CALIBRATION_ERROR",
                    "bins": CALIBRATION_BIN_COUNT,
                    "binning": "EQUAL_WIDTH_0_TO_1",
                },
                "latency": "AI_PROVIDER_HTTP_LATENCY_SECONDS_ALL_ATTEMPTS",
                "market_comparison": "VIG_REMOVED_TWO_WAY_PROBABILITY_AT_DECISION_SNAPSHOT",
                "significance": "DESCRIPTIVE_ONLY_NO_STATISTICAL_SIGNIFICANCE_CLAIM",
                "experiment_identity": "INCLUDES_FROZEN_EXECUTION_CONFIG_VERSION",
            },
            "experiments": experiments,
        }

    def _build_experiment_row(
        self,
        key: ExperimentKey,
        acc: _ExperimentAccumulator,
        portfolio: dict[str, Any] | None,
    ) -> dict[str, Any]:
        forecast_samples = list(acc.forecast_by_map.values())
        probabilities = [sample[0] for sample in forecast_samples]
        outcomes = [sample[1] for sample in forecast_samples]
        briers = [sample[2] for sample in forecast_samples]
        log_losses = [sample[3] for sample in forecast_samples]
        comparable = [sample for sample in forecast_samples if sample[4] is not None]
        market_briers = [
            (float(sample[4]) - float(sample[1])) ** 2
            for sample in comparable
            if sample[4] is not None
        ]
        comparable_ai_briers = [sample[2] for sample in comparable]
        accuracy = _average(
            [
                1.0 if ((probability >= 0.5) == outcome) else 0.0
                for probability, outcome in zip(probabilities, outcomes, strict=True)
            ]
        )
        abstentions = sum(acc.action_counts[action] for action in ("NO_BUY", "INSUFFICIENT_DATA"))
        action_total = sum(acc.action_counts.values())
        portfolio_metrics = _portfolio_metrics(portfolio)
        return {
            "experiment": _identity_dict(key),
            "observed_model_versions": sorted(acc.model_versions),
            "execution_config": {
                "version": key[5],
                "mixed": False,
                "comparison_eligible": True,
                "blocker": None,
            },
            "baseline_role": "BASELINE" if _is_baseline_key(key) else "CHALLENGER",
            "samples": {
                "attempts": acc.attempts,
                "successful_decisions": acc.successful_attempts,
                "parse_success_rate": (
                    acc.successful_attempts / acc.attempts if acc.attempts else None
                ),
                "forecast_maps": len(forecast_samples),
                "clv_maps": len(acc.clv_by_map),
                "market_comparison_maps": len(comparable),
            },
            "quality": {
                "forecast_accuracy": accuracy,
                "average_brier_score": _average(briers),
                "average_log_loss": _average(log_losses),
                "calibration_error": _expected_calibration_error(probabilities, outcomes),
                "average_clv": _average(list(acc.clv_by_map.values())),
                "market_brier_improvement": _difference(
                    _average(market_briers),
                    _average(comparable_ai_briers),
                ),
                "abstention_rate": (
                    abstentions / action_total if action_total else None
                ),
                "action_counts": dict(sorted(acc.action_counts.items())),
                "parse_status_counts": dict(sorted(acc.parse_statuses.items())),
            },
            "latency": {
                "sample_count": len(acc.latencies),
                "average_seconds": _average(acc.latencies),
                "p95_seconds": _percentile(acc.latencies, 0.95),
            },
            "portfolio": portfolio_metrics,
            "baseline_reference": None,
            "delta_vs_baseline": None,
        }


def _baseline_contract() -> dict[str, Any]:
    return {
        "id": BASELINE_ID,
        "frozen_at_commit": BASELINE_FROZEN_AT_COMMIT,
        "prompt_version": BASELINE_PROMPT_VERSION,
        "decision_policy_version": BASELINE_DECISION_POLICY_VERSION,
        "ai_view_version": BASELINE_AI_VIEW_VERSION,
        "models_by_provider": dict(BASELINE_MODELS_BY_PROVIDER),
        "immutable": True,
    }


def _identity_key(record: AiDecisionRecord) -> ExperimentKey:
    return (
        record.provider,
        record.model,
        record.prompt_version,
        record.decision_policy_version,
        record.ai_view_version,
        record.execution_config_version,
    )


def _identity_key_from_dict(identity: dict[str, Any]) -> ExperimentKey:
    return (
        str(identity["provider"]),
        str(identity["model"]),
        str(identity["prompt_version"]),
        str(identity["decision_policy_version"]),
        str(identity["ai_view_version"]),
        str(identity["execution_config_version"]),
    )


def _identity_dict(key: ExperimentKey) -> dict[str, str]:
    return {
        "provider": key[0],
        "model": key[1],
        "prompt_version": key[2],
        "decision_policy_version": key[3],
        "ai_view_version": key[4],
        "execution_config_version": key[5],
    }


def _baseline_key_for_provider(
    provider: str,
    execution_config_version: str,
) -> ExperimentKey | None:
    model = BASELINE_MODELS_BY_PROVIDER.get(provider)
    if model is None:
        return None
    return (
        provider,
        model,
        BASELINE_PROMPT_VERSION,
        BASELINE_DECISION_POLICY_VERSION,
        BASELINE_AI_VIEW_VERSION,
        execution_config_version,
    )


def _is_baseline_key(key: ExperimentKey) -> bool:
    baseline = _baseline_key_for_provider(key[0], key[5])
    return baseline == key


def _portfolio_metrics(portfolio: dict[str, Any] | None) -> dict[str, Any]:
    if portfolio is None:
        return {
            "event_count": 0,
            "realized_roi": None,
            "realized_pnl": None,
            "worst_event_drawdown_pct": None,
            "bet_count": 0,
        }
    return {
        "event_count": portfolio["event_count"],
        "realized_roi": portfolio["realized_roi"],
        "realized_pnl": portfolio["realized_pnl"],
        "worst_event_drawdown_pct": portfolio["worst_event_drawdown_pct"],
        "bet_count": portfolio["bet_count"],
    }


def _comparison_delta(baseline: dict[str, Any], challenger: dict[str, Any]) -> dict[str, Any]:
    baseline_quality = baseline["quality"]
    challenger_quality = challenger["quality"]
    baseline_latency = baseline["latency"]
    challenger_latency = challenger["latency"]
    baseline_portfolio = baseline["portfolio"]
    challenger_portfolio = challenger["portfolio"]
    return {
        "forecast_maps": challenger["samples"]["forecast_maps"]
        - baseline["samples"]["forecast_maps"],
        "forecast_accuracy": _delta(
            challenger_quality["forecast_accuracy"], baseline_quality["forecast_accuracy"]
        ),
        "brier_improvement": _delta(
            baseline_quality["average_brier_score"], challenger_quality["average_brier_score"]
        ),
        "log_loss_improvement": _delta(
            baseline_quality["average_log_loss"], challenger_quality["average_log_loss"]
        ),
        "calibration_improvement": _delta(
            baseline_quality["calibration_error"], challenger_quality["calibration_error"]
        ),
        "clv_improvement": _delta(
            challenger_quality["average_clv"], baseline_quality["average_clv"]
        ),
        "market_brier_improvement_delta": _delta(
            challenger_quality["market_brier_improvement"],
            baseline_quality["market_brier_improvement"],
        ),
        "abstention_rate_delta": _delta(
            challenger_quality["abstention_rate"], baseline_quality["abstention_rate"]
        ),
        "average_latency_improvement_seconds": _delta(
            baseline_latency["average_seconds"], challenger_latency["average_seconds"]
        ),
        "p95_latency_improvement_seconds": _delta(
            baseline_latency["p95_seconds"], challenger_latency["p95_seconds"]
        ),
        "shadow_roi_delta": _delta(
            challenger_portfolio["realized_roi"], baseline_portfolio["realized_roi"]
        ),
        "drawdown_improvement": _delta(
            baseline_portfolio["worst_event_drawdown_pct"],
            challenger_portfolio["worst_event_drawdown_pct"],
        ),
    }


def _expected_calibration_error(probabilities: list[float], outcomes: list[bool]) -> float | None:
    if not probabilities:
        return None
    bins: list[list[tuple[float, bool]]] = [[] for _ in range(CALIBRATION_BIN_COUNT)]
    for probability, outcome in zip(probabilities, outcomes, strict=True):
        index = min(int(probability * CALIBRATION_BIN_COUNT), CALIBRATION_BIN_COUNT - 1)
        bins[index].append((probability, outcome))
    total = len(probabilities)
    error = 0.0
    for bucket in bins:
        if not bucket:
            continue
        confidence = sum(item[0] for item in bucket) / len(bucket)
        observed = sum(float(item[1]) for item in bucket) / len(bucket)
        error += (len(bucket) / total) * abs(confidence - observed)
    return error


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


def _average(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _difference(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return left - right


def _delta(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return left - right


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight
