from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from statistics import mean
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from app.models import (
    AiDecisionRecord,
    CanonicalEvent,
    CanonicalMap,
    CanonicalSeries,
    CanonicalTeam,
    DecisionEvaluationRecord,
    DecisionSnapshotRecord,
)

EXPERIMENT_IDENTITY_FIELDS = (
    "provider",
    "model",
    "model_version",
    "prompt_version",
    "decision_policy_version",
    "ai_view_version",
    "execution_config_version",
)


async def build_ai_performance_payload(
    session: AsyncSession,
    *,
    limit: int = 1000,
    offset: int = 0,
) -> dict[str, Any]:
    """Build the user-facing, auditable projection for AI experiment performance.

    Every row is derived only from frozen DecisionSnapshot / AiDecision / Evaluation
    records. The projection deliberately keeps experiment versions separate instead
    of silently merging a new prompt, policy, model, or AI-view implementation into
    older results.
    """

    decision_page = list(
        (
            await session.scalars(
                select(AiDecisionRecord)
                .options(
                    load_only(
                        AiDecisionRecord.id,
                        AiDecisionRecord.snapshot_id,
                        AiDecisionRecord.snapshot_hash,
                        AiDecisionRecord.provider,
                        AiDecisionRecord.model,
                        AiDecisionRecord.model_version,
                        AiDecisionRecord.prompt_version,
                        AiDecisionRecord.decision_policy_version,
                        AiDecisionRecord.ai_view_version,
                        AiDecisionRecord.execution_config_version,
                        AiDecisionRecord.ai_input_hash,
                        AiDecisionRecord.bankroll_before,
                        AiDecisionRecord.stake,
                        AiDecisionRecord.job_enqueued_at,
                        AiDecisionRecord.job_claimed_at,
                        AiDecisionRecord.input_prepare_started_at,
                        AiDecisionRecord.input_prepare_completed_at,
                        AiDecisionRecord.request_started_at,
                        AiDecisionRecord.response_received_at,
                        AiDecisionRecord.latency_seconds,
                        AiDecisionRecord.input_tokens,
                        AiDecisionRecord.cached_input_tokens,
                        AiDecisionRecord.reasoning_tokens,
                        AiDecisionRecord.output_tokens,
                        AiDecisionRecord.total_tokens,
                        AiDecisionRecord.decision_persisted_at,
                        AiDecisionRecord.normalized_response,
                        AiDecisionRecord.parse_status,
                        AiDecisionRecord.error,
                    )
                )
                .order_by(
                    AiDecisionRecord.request_started_at.desc(),
                    AiDecisionRecord.id.desc(),
                )
                .offset(offset)
                .limit(limit + 1)
            )
        ).all()
    )
    has_more = len(decision_page) > limit
    decisions = decision_page[:limit]
    if not decisions:
        return _empty_payload(limit, offset=offset, has_more=False)

    decision_ids = [record.id for record in decisions]
    snapshot_ids = list({record.snapshot_id for record in decisions})

    evaluations = list(
        (
            await session.scalars(
                select(DecisionEvaluationRecord)
                .where(DecisionEvaluationRecord.ai_decision_id.in_(decision_ids))
                .options(
                    load_only(
                        DecisionEvaluationRecord.ai_decision_id,
                        DecisionEvaluationRecord.result_correct,
                        DecisionEvaluationRecord.brier_score,
                        DecisionEvaluationRecord.log_loss,
                        DecisionEvaluationRecord.clv,
                        DecisionEvaluationRecord.future_odds_direction,
                        DecisionEvaluationRecord.virtual_pnl,
                        DecisionEvaluationRecord.virtual_odds,
                        DecisionEvaluationRecord.unit_pnl,
                        DecisionEvaluationRecord.evaluated_at,
                        DecisionEvaluationRecord.metrics_version,
                    )
                )
            )
        ).all()
    )
    evaluation_by_decision = {record.ai_decision_id: record for record in evaluations}

    snapshots = list(
        (
            await session.scalars(
                select(DecisionSnapshotRecord)
                .options(
                    load_only(
                        DecisionSnapshotRecord.id,
                        DecisionSnapshotRecord.canonical_map_id,
                        DecisionSnapshotRecord.decision_at,
                        DecisionSnapshotRecord.mode,
                    )
                )
                .where(DecisionSnapshotRecord.id.in_(snapshot_ids))
            )
        ).all()
    )
    snapshot_by_id = {record.id: record for record in snapshots}
    match_context_by_map = await _load_match_contexts(session, snapshots)

    experiments = _build_experiment_groups(
        decisions,
        evaluation_by_decision=evaluation_by_decision,
    )
    traces = [
        _decision_trace_payload(
            record,
            snapshot=snapshot_by_id.get(record.snapshot_id),
            evaluation=evaluation_by_decision.get(record.id),
            match_context_by_map=match_context_by_map,
        )
        for record in decisions
    ]

    successful = [record for record in decisions if _successful(record)]
    evaluated = [
        record for record in successful if evaluation_by_decision.get(record.id) is not None
    ]
    settled_buys = [
        record
        for record in successful
        if _is_buy(record)
        and evaluation_by_decision.get(record.id) is not None
        and evaluation_by_decision[record.id].result_correct is not None
    ]
    correct_buys = [
        record
        for record in settled_buys
        if evaluation_by_decision[record.id].result_correct is True
    ]
    brier_values = [
        evaluation_by_decision[record.id].brier_score
        for record in evaluated
        if evaluation_by_decision[record.id].brier_score is not None
    ]
    log_loss_values = [
        evaluation_by_decision[record.id].log_loss
        for record in evaluated
        if evaluation_by_decision[record.id].log_loss is not None
    ]
    unit_values = [
        float(evaluation_by_decision[record.id].unit_pnl)
        for record in successful
        if _is_buy(record)
        and evaluation_by_decision.get(record.id) is not None
        and evaluation_by_decision[record.id].unit_pnl is not None
    ]

    return {
        "summary": {
            "attempts": len(decisions),
            "successful": len(successful),
            "success_rate": len(successful) / len(decisions),
            "evaluated": len(evaluated),
            "settled_buy_decisions": len(settled_buys),
            "correct_buy_decisions": len(correct_buys),
            "buy_accuracy": len(correct_buys) / len(settled_buys) if settled_buys else None,
            "average_brier": mean(brier_values) if brier_values else None,
            "average_log_loss": mean(log_loss_values) if log_loss_values else None,
            "unit_pnl": round(sum(unit_values), 4) if unit_values else None,
            "unit_bets": len(unit_values),
            "unit_roi": sum(unit_values) / len(unit_values) if unit_values else None,
            "experiment_count": len(experiments),
        },
        "experiments": experiments,
        "decisions": traces,
        "pagination": {
            "limit": limit,
            "offset": offset,
            "returned": len(decisions),
            "has_more": has_more,
            "next_offset": offset + len(decisions) if has_more else None,
        },
        "methodology": {
            "query_limit": limit,
            "experiment_identity": list(EXPERIMENT_IDENTITY_FIELDS),
            "comparison_rule": "KEEP_EACH_EXPERIMENT_VERSION_SEPARATE",
            "buy_accuracy": "SETTLED_BUY_DECISIONS_ONLY",
            "probability_quality": "BRIER_AND_LOG_LOSS_FROM_DECISION_EVALUATIONS",
            "unit_roi": "SUM_1_UNIT_PNL_DIVIDED_BY_SETTLED_1_UNIT_BETS",
            "audit_identity": "SNAPSHOT_HASH_PLUS_AI_INPUT_HASH_PLUS_EXPERIMENT_VERSIONS",
            "source": "IMMUTABLE_DECISION_SNAPSHOT_AND_FROZEN_AI_DECISION",
            "no_future_leakage": True,
        },
    }


def _empty_payload(limit: int, *, offset: int, has_more: bool) -> dict[str, Any]:
    return {
        "summary": {
            "attempts": 0,
            "successful": 0,
            "success_rate": None,
            "evaluated": 0,
            "settled_buy_decisions": 0,
            "correct_buy_decisions": 0,
            "buy_accuracy": None,
            "average_brier": None,
            "average_log_loss": None,
            "unit_pnl": None,
            "unit_bets": 0,
            "unit_roi": None,
            "experiment_count": 0,
        },
        "experiments": [],
        "decisions": [],
        "pagination": {
            "limit": limit,
            "offset": offset,
            "returned": 0,
            "has_more": has_more,
            "next_offset": offset if has_more else None,
        },
        "methodology": {
            "query_limit": limit,
            "experiment_identity": list(EXPERIMENT_IDENTITY_FIELDS),
            "comparison_rule": "KEEP_EACH_EXPERIMENT_VERSION_SEPARATE",
            "buy_accuracy": "SETTLED_BUY_DECISIONS_ONLY",
            "probability_quality": "BRIER_AND_LOG_LOSS_FROM_DECISION_EVALUATIONS",
            "unit_roi": "SUM_1_UNIT_PNL_DIVIDED_BY_SETTLED_1_UNIT_BETS",
            "audit_identity": "SNAPSHOT_HASH_PLUS_AI_INPUT_HASH_PLUS_EXPERIMENT_VERSIONS",
            "source": "IMMUTABLE_DECISION_SNAPSHOT_AND_FROZEN_AI_DECISION",
            "no_future_leakage": True,
        },
    }


def _experiment_key(record: AiDecisionRecord) -> tuple[str, ...]:
    return (
        record.provider,
        record.model,
        record.model_version,
        record.prompt_version,
        record.decision_policy_version,
        record.ai_view_version,
        record.execution_config_version,
    )


def _experiment_id(key: tuple[str, ...]) -> str:
    return "::".join(key)


def _build_experiment_groups(
    decisions: list[AiDecisionRecord],
    *,
    evaluation_by_decision: dict[UUID, DecisionEvaluationRecord],
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, ...], list[AiDecisionRecord]] = defaultdict(list)
    for record in decisions:
        grouped[_experiment_key(record)].append(record)

    payloads: list[dict[str, Any]] = []
    for key, records in grouped.items():
        successful = [record for record in records if _successful(record)]
        failed = [record for record in records if not _successful(record)]
        buys = [record for record in successful if _is_buy(record)]
        settled_buys = [
            record
            for record in buys
            if evaluation_by_decision.get(record.id) is not None
            and evaluation_by_decision[record.id].result_correct is not None
        ]
        correct_buys = [
            record
            for record in settled_buys
            if evaluation_by_decision[record.id].result_correct is True
        ]
        evaluated = [
            record for record in successful if evaluation_by_decision.get(record.id) is not None
        ]
        brier_values = [
            evaluation_by_decision[record.id].brier_score
            for record in evaluated
            if evaluation_by_decision[record.id].brier_score is not None
        ]
        log_loss_values = [
            evaluation_by_decision[record.id].log_loss
            for record in evaluated
            if evaluation_by_decision[record.id].log_loss is not None
        ]
        unit_values = [
            float(evaluation_by_decision[record.id].unit_pnl)
            for record in buys
            if evaluation_by_decision.get(record.id) is not None
            and evaluation_by_decision[record.id].unit_pnl is not None
        ]
        latencies = [
            record.latency_seconds for record in records if record.latency_seconds is not None
        ]
        end_to_end = [
            seconds
            for record in records
            if (seconds := _duration_seconds(record.job_enqueued_at, record.decision_persisted_at))
            is not None
        ]
        total_tokens = [
            record.total_tokens for record in records if record.total_tokens is not None
        ]
        input_token_total = sum(
            record.input_tokens for record in records if record.input_tokens is not None
        )
        cached_token_total = sum(
            record.cached_input_tokens
            for record in records
            if record.cached_input_tokens is not None
        )
        latest = max(records, key=lambda item: item.request_started_at)

        payloads.append(
            {
                "id": _experiment_id(key),
                "provider": key[0],
                "model": key[1],
                "model_version": key[2],
                "prompt_version": key[3],
                "decision_policy_version": key[4],
                "ai_view_version": key[5],
                "execution_config_version": key[6],
                "attempts": len(records),
                "successful": len(successful),
                "failed": len(failed),
                "success_rate": len(successful) / len(records) if records else None,
                "evaluated": len(evaluated),
                "buy_decisions": len(buys),
                "settled_buy_decisions": len(settled_buys),
                "correct_buy_decisions": len(correct_buys),
                "buy_accuracy": len(correct_buys) / len(settled_buys) if settled_buys else None,
                "average_brier": mean(brier_values) if brier_values else None,
                "average_log_loss": mean(log_loss_values) if log_loss_values else None,
                "unit_pnl": round(sum(unit_values), 4) if unit_values else None,
                "unit_bets": len(unit_values),
                "unit_roi": sum(unit_values) / len(unit_values) if unit_values else None,
                "average_latency_seconds": mean(latencies) if latencies else None,
                "p95_latency_seconds": _percentile(latencies, 0.95),
                "average_end_to_end_seconds": mean(end_to_end) if end_to_end else None,
                "average_total_tokens": mean(total_tokens) if total_tokens else None,
                "cached_input_ratio": (
                    cached_token_total / input_token_total if input_token_total > 0 else None
                ),
                "last_decision_at": latest.request_started_at,
            }
        )

    payloads.sort(
        key=lambda item: (
            item["last_decision_at"],
            item["provider"],
            item["model"],
        ),
        reverse=True,
    )
    return payloads


def _decision_trace_payload(
    record: AiDecisionRecord,
    *,
    snapshot: DecisionSnapshotRecord | None,
    evaluation: DecisionEvaluationRecord | None,
    match_context_by_map: dict[UUID, dict[str, Any]],
) -> dict[str, Any]:
    normalized = record.normalized_response if isinstance(record.normalized_response, dict) else {}
    map_id = snapshot.canonical_map_id if snapshot is not None else None
    match = match_context_by_map.get(map_id) if map_id is not None else None
    return {
        "id": str(record.id),
        "experiment_id": _experiment_id(_experiment_key(record)),
        "snapshot_id": str(record.snapshot_id),
        "canonical_map_id": str(map_id) if map_id is not None else None,
        "match": match,
        "decision_at": snapshot.decision_at if snapshot is not None else record.request_started_at,
        "mode": snapshot.mode if snapshot is not None else None,
        "snapshot_hash": record.snapshot_hash,
        "ai_input_hash": record.ai_input_hash,
        "provider": record.provider,
        "model": record.model,
        "model_version": record.model_version,
        "prompt_version": record.prompt_version,
        "decision_policy_version": record.decision_policy_version,
        "ai_view_version": record.ai_view_version,
        "execution_config_version": record.execution_config_version,
        "parse_status": record.parse_status,
        "error": record.error,
        "action": normalized.get("action"),
        "fair_probability_a": _number(normalized.get("fair_probability_a")),
        "confidence": _number(normalized.get("confidence")),
        "market_assessment": normalized.get("market_assessment"),
        "primary_reasons": _string_list(normalized.get("primary_reasons")),
        "blockers": _string_list(normalized.get("blockers")),
        "bankroll_before": _decimal_number(record.bankroll_before),
        "stake": _decimal_number(record.stake),
        "trace": {
            "job_enqueued_at": record.job_enqueued_at,
            "job_claimed_at": record.job_claimed_at,
            "input_prepare_started_at": record.input_prepare_started_at,
            "input_prepare_completed_at": record.input_prepare_completed_at,
            "request_started_at": record.request_started_at,
            "response_received_at": record.response_received_at,
            "decision_persisted_at": record.decision_persisted_at,
            "provider_latency_seconds": record.latency_seconds,
            "queue_seconds": _duration_seconds(record.job_enqueued_at, record.job_claimed_at),
            "input_prepare_seconds": _duration_seconds(
                record.input_prepare_started_at,
                record.input_prepare_completed_at,
            ),
            "end_to_end_seconds": _duration_seconds(
                record.job_enqueued_at,
                record.decision_persisted_at,
            ),
        },
        "tokens": {
            "input": record.input_tokens,
            "cached_input": record.cached_input_tokens,
            "reasoning": record.reasoning_tokens,
            "output": record.output_tokens,
            "total": record.total_tokens,
        },
        "evaluation": (
            {
                "result_correct": evaluation.result_correct,
                "brier_score": evaluation.brier_score,
                "log_loss": evaluation.log_loss,
                "clv": evaluation.clv,
                "future_odds_direction": evaluation.future_odds_direction,
                "virtual_pnl": _decimal_number(evaluation.virtual_pnl),
                "virtual_odds": _decimal_number(evaluation.virtual_odds),
                "unit_pnl": _decimal_number(evaluation.unit_pnl),
                "evaluated_at": evaluation.evaluated_at,
                "metrics_version": evaluation.metrics_version,
            }
            if evaluation is not None
            else None
        ),
    }


async def _load_match_contexts(
    session: AsyncSession,
    snapshots: list[DecisionSnapshotRecord],
) -> dict[UUID, dict[str, Any]]:
    map_ids = list(
        {
            snapshot.canonical_map_id
            for snapshot in snapshots
            if snapshot.canonical_map_id is not None
        }
    )
    if not map_ids:
        return {}

    maps = list(
        (
            await session.scalars(
                select(CanonicalMap)
                .options(
                    load_only(
                        CanonicalMap.id,
                        CanonicalMap.series_id,
                        CanonicalMap.map_number,
                        CanonicalMap.valve_match_id,
                    )
                )
                .where(CanonicalMap.id.in_(map_ids))
            )
        ).all()
    )
    series_ids = list({record.series_id for record in maps if record.series_id is not None})
    series = (
        list(
            (
                await session.scalars(
                    select(CanonicalSeries)
                    .options(
                        load_only(
                            CanonicalSeries.id,
                            CanonicalSeries.event_id,
                            CanonicalSeries.team_a_id,
                            CanonicalSeries.team_b_id,
                        )
                    )
                    .where(CanonicalSeries.id.in_(series_ids))
                )
            ).all()
        )
        if series_ids
        else []
    )
    series_by_id = {record.id: record for record in series}

    team_ids = list(
        {team_id for record in series for team_id in (record.team_a_id, record.team_b_id)}
    )
    teams = (
        list(
            (
                await session.scalars(
                    select(CanonicalTeam)
                    .options(load_only(CanonicalTeam.id, CanonicalTeam.name))
                    .where(CanonicalTeam.id.in_(team_ids))
                )
            ).all()
        )
        if team_ids
        else []
    )
    team_by_id = {record.id: record for record in teams}

    event_ids = list({record.event_id for record in series if record.event_id is not None})
    events = (
        list(
            (
                await session.scalars(
                    select(CanonicalEvent)
                    .options(load_only(CanonicalEvent.id, CanonicalEvent.name))
                    .where(CanonicalEvent.id.in_(event_ids))
                )
            ).all()
        )
        if event_ids
        else []
    )
    event_by_id = {record.id: record for record in events}

    payloads: dict[UUID, dict[str, Any]] = {}
    for canonical_map in maps:
        series_record = (
            series_by_id.get(canonical_map.series_id)
            if canonical_map.series_id is not None
            else None
        )
        if series_record is None:
            payloads[canonical_map.id] = {
                "map_number": canonical_map.map_number,
                "valve_match_id": canonical_map.valve_match_id,
                "tournament_name": None,
                "team_a": None,
                "team_b": None,
            }
            continue
        team_a = team_by_id.get(series_record.team_a_id)
        team_b = team_by_id.get(series_record.team_b_id)
        event = (
            event_by_id.get(series_record.event_id) if series_record.event_id is not None else None
        )
        payloads[canonical_map.id] = {
            "map_number": canonical_map.map_number,
            "valve_match_id": canonical_map.valve_match_id,
            "tournament_name": event.name if event is not None else None,
            "team_a": ({"id": str(team_a.id), "name": team_a.name} if team_a is not None else None),
            "team_b": ({"id": str(team_b.id), "name": team_b.name} if team_b is not None else None),
        }
    return payloads


def _successful(record: AiDecisionRecord) -> bool:
    return record.parse_status == "SUCCESS" and isinstance(record.normalized_response, dict)


def _is_buy(record: AiDecisionRecord) -> bool:
    payload = record.normalized_response
    return isinstance(payload, dict) and payload.get("action") in {"BUY_A", "BUY_B"}


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int((len(ordered) - 1) * percentile + 0.5)))
    return ordered[index]


def _duration_seconds(start: datetime | None, end: datetime | None) -> float | None:
    if start is None or end is None:
        return None
    return max(0.0, (end - start).total_seconds())


def _number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _decimal_number(value: object) -> float | None:
    return float(value) if value is not None else None


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]
