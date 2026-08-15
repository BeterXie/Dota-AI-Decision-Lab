import asyncio
from collections import defaultdict
from statistics import mean
from time import monotonic
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ai.eligibility import ai_record_is_game_time_eligible
from app.market.fair_probability import remove_vig
from app.models import (
    AiDecisionRecord,
    CanonicalEvent,
    CanonicalMap,
    CanonicalSeries,
    CanonicalTeam,
    DecisionEvaluationRecord,
    DecisionFutureOdds,
    DecisionSnapshotRecord,
    MapResultRecord,
)

ROSH_REFERENCE_MINUTE = 30
ROSH_REVIEW_MINUTES = (20, 30, 40)
REVIEW_CACHE_TTL_SECONDS = 15.0
_ROSH_EVEN_EPSILON = 0.05


def create_review_router(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    ai_min_game_time_seconds: int = 600,
    cache_ttl_seconds: float = REVIEW_CACHE_TTL_SECONDS,
) -> APIRouter:
    router = APIRouter()
    cache: dict[int, tuple[float, dict[str, Any]]] = {}
    cache_lock = asyncio.Lock()

    @router.get("/api/review/matches")
    async def review_matches(
        limit: int = Query(default=100, ge=1, le=200),
    ) -> dict[str, Any]:
        now = monotonic()
        cached = cache.get(limit)
        if cached is not None and now - cached[0] < cache_ttl_seconds:
            return cached[1]
        async with cache_lock:
            now = monotonic()
            cached = cache.get(limit)
            if cached is not None and now - cached[0] < cache_ttl_seconds:
                return cached[1]
            async with session_factory() as session:
                payload = await build_review_payload(
                    session,
                    limit=limit,
                    ai_min_game_time_seconds=ai_min_game_time_seconds,
                )
            cache[limit] = (monotonic(), payload)
            return payload

    return router


async def build_review_payload(
    session: AsyncSession,
    *,
    limit: int = 100,
    ai_min_game_time_seconds: int = 600,
) -> dict[str, Any]:
    """Build a post-match review projection from immutable/audited records.

    R.O.S.H. values come from the earliest immutable DecisionSnapshot that
    already contained a complete curve and resolved map sides. That prevents a
    later draft recomputation from leaking post-match historical information
    into the review. AI attempts are canonicalized exactly once per
    snapshot/provider/model before accuracy is aggregated.
    """

    results = list(
        (
            await session.scalars(
                select(MapResultRecord)
                .where(
                    MapResultRecord.winner_team_id.is_not(None),
                    MapResultRecord.provider_conflict.is_(False),
                )
                .order_by(MapResultRecord.settled_at.desc())
                .limit(limit)
            )
        ).all()
    )
    if not results:
        return _empty_payload()

    map_ids = [item.canonical_map_id for item in results]
    maps = list(
        (await session.scalars(select(CanonicalMap).where(CanonicalMap.id.in_(map_ids)))).all()
    )
    map_by_id = {item.id: item for item in maps}

    series_ids = list({item.series_id for item in maps if item.series_id is not None})
    series_rows = (
        list(
            (
                await session.scalars(
                    select(CanonicalSeries).where(CanonicalSeries.id.in_(series_ids))
                )
            ).all()
        )
        if series_ids
        else []
    )
    series_by_id = {item.id: item for item in series_rows}

    team_ids = list(
        {team_id for series in series_rows for team_id in (series.team_a_id, series.team_b_id)}
    )
    teams = (
        list(
            (
                await session.scalars(select(CanonicalTeam).where(CanonicalTeam.id.in_(team_ids)))
            ).all()
        )
        if team_ids
        else []
    )
    team_by_id = {item.id: item for item in teams}

    event_ids = list({item.event_id for item in series_rows if item.event_id is not None})
    events = (
        list(
            (
                await session.scalars(
                    select(CanonicalEvent).where(CanonicalEvent.id.in_(event_ids))
                )
            ).all()
        )
        if event_ids
        else []
    )
    event_by_id = {item.id: item for item in events}

    snapshots = list(
        (
            await session.scalars(
                select(DecisionSnapshotRecord)
                .where(DecisionSnapshotRecord.canonical_map_id.in_(map_ids))
                .order_by(
                    DecisionSnapshotRecord.canonical_map_id,
                    DecisionSnapshotRecord.decision_at,
                )
            )
        ).all()
    )
    snapshots_by_map: dict[UUID, list[DecisionSnapshotRecord]] = defaultdict(list)
    snapshot_by_id: dict[UUID, DecisionSnapshotRecord] = {}
    for snapshot in snapshots:
        if snapshot.canonical_map_id is not None:
            snapshots_by_map[snapshot.canonical_map_id].append(snapshot)
        snapshot_by_id[snapshot.id] = snapshot

    snapshot_ids = list(snapshot_by_id)
    decision_rows = (
        list(
            (
                await session.scalars(
                    select(AiDecisionRecord).where(AiDecisionRecord.snapshot_id.in_(snapshot_ids))
                )
            ).all()
        )
        if snapshot_ids
        else []
    )
    canonical_decisions = _canonical_decision_rounds(decision_rows)
    decision_ids = [item.id for item in canonical_decisions]
    evaluations = (
        list(
            (
                await session.scalars(
                    select(DecisionEvaluationRecord).where(
                        DecisionEvaluationRecord.ai_decision_id.in_(decision_ids)
                    )
                )
            ).all()
        )
        if decision_ids
        else []
    )
    evaluation_by_decision = {item.ai_decision_id: item for item in evaluations}

    closing_rows = (
        list(
            (
                await session.scalars(
                    select(DecisionFutureOdds).where(
                        DecisionFutureOdds.decision_snapshot_id.in_(snapshot_ids),
                        DecisionFutureOdds.capture_type == "CLOSING",
                        DecisionFutureOdds.status == "CAPTURED",
                    )
                )
            ).all()
        )
        if snapshot_ids
        else []
    )
    closings_by_map: dict[UUID, list[DecisionFutureOdds]] = defaultdict(list)
    for closing in closing_rows:
        snapshot = snapshot_by_id.get(closing.decision_snapshot_id)
        if snapshot is not None and snapshot.canonical_map_id is not None:
            closings_by_map[snapshot.canonical_map_id].append(closing)

    decisions_by_map: dict[UUID, list[AiDecisionRecord]] = defaultdict(list)
    for decision in canonical_decisions:
        snapshot = snapshot_by_id.get(decision.snapshot_id)
        if snapshot is not None and snapshot.canonical_map_id is not None:
            decisions_by_map[snapshot.canonical_map_id].append(decision)

    rows: list[dict[str, Any]] = []
    for result in results:
        canonical_map = map_by_id.get(result.canonical_map_id)
        if canonical_map is None or canonical_map.series_id is None:
            continue
        series = series_by_id.get(canonical_map.series_id)
        if series is None:
            continue
        team_a = team_by_id.get(series.team_a_id)
        team_b = team_by_id.get(series.team_b_id)
        if team_a is None or team_b is None:
            continue
        map_snapshots = snapshots_by_map.get(canonical_map.id, [])
        map_decisions = decisions_by_map.get(canonical_map.id, [])
        event = event_by_id.get(series.event_id) if series.event_id is not None else None
        rows.append(
            {
                "canonical_map_id": str(canonical_map.id),
                "series_id": str(series.id),
                "map_number": canonical_map.map_number,
                "valve_match_id": canonical_map.valve_match_id,
                "scheduled_at": canonical_map.scheduled_at or series.scheduled_at,
                "settled_at": result.settled_at,
                "tournament_name": event.name if event is not None else None,
                "team_a": {"id": str(team_a.id), "name": team_a.name},
                "team_b": {"id": str(team_b.id), "name": team_b.name},
                "winner_team_id": str(result.winner_team_id),
                "rosh": _rosh_review(map_snapshots, winner_team_id=result.winner_team_id),
                "ai": _ai_groups(
                    map_decisions,
                    evaluation_by_decision=evaluation_by_decision,
                    snapshot_by_id=snapshot_by_id,
                ),
                "odds": _odds_review(
                    map_snapshots,
                    closings=closings_by_map.get(canonical_map.id, []),
                    ai_min_game_time_seconds=ai_min_game_time_seconds,
                ),
            }
        )

    return {
        "summary": _review_summary(
            rows,
            ai=_ai_groups(
                canonical_decisions,
                evaluation_by_decision=evaluation_by_decision,
                snapshot_by_id=snapshot_by_id,
            ),
        ),
        "matches": rows,
        "methodology": {
            "rosh_reference_minute": ROSH_REFERENCE_MINUTE,
            "rosh_review_minutes": list(ROSH_REVIEW_MINUTES),
            "rosh_source": "EARLIEST_IMMUTABLE_DECISION_SNAPSHOT_WITH_RESOLVED_SIDES",
            "ai_round_rule": "LATEST_SUCCESS_PER_SNAPSHOT_PROVIDER_MODEL",
            "odds_start": "EARLIEST_AI_ELIGIBLE_SNAPSHOT_WITH_ELIGIBLE_MARKET",
            "odds_end": "CLOSING_CAPTURE_OR_LATEST_VALID_DECISION_SNAPSHOT",
        },
    }


def _empty_payload() -> dict[str, Any]:
    return {
        "summary": {
            "settled_maps": 0,
            "rosh": {
                "reference_minute": ROSH_REFERENCE_MINUTE,
                "pure": {"evaluated": 0, "correct": 0, "accuracy": None},
                "adjusted": {"evaluated": 0, "correct": 0, "accuracy": None},
            },
            "ai": [],
            "odds": {"eligible_maps": 0, "closing_captured": 0, "closing_coverage": None},
        },
        "matches": [],
        "methodology": {
            "rosh_reference_minute": ROSH_REFERENCE_MINUTE,
            "rosh_review_minutes": list(ROSH_REVIEW_MINUTES),
            "rosh_source": "EARLIEST_IMMUTABLE_DECISION_SNAPSHOT_WITH_RESOLVED_SIDES",
            "ai_round_rule": "LATEST_SUCCESS_PER_SNAPSHOT_PROVIDER_MODEL",
            "odds_start": "EARLIEST_AI_ELIGIBLE_SNAPSHOT_WITH_ELIGIBLE_MARKET",
            "odds_end": "CLOSING_CAPTURE_OR_LATEST_VALID_DECISION_SNAPSHOT",
        },
    }


def _canonical_decision_rounds(records: list[AiDecisionRecord]) -> list[AiDecisionRecord]:
    best: dict[tuple[UUID, str, str], tuple[tuple[Any, ...], AiDecisionRecord]] = {}
    for record in records:
        if record.parse_status != "SUCCESS" or record.normalized_response is None:
            continue
        key = (record.snapshot_id, record.provider, record.model)
        attempt = (
            record.request_started_at,
            record.prompt_version,
            record.decision_policy_version,
            record.ai_view_version,
        )
        current = best.get(key)
        if current is None or attempt > current[0]:
            best[key] = (attempt, record)
    return [record for _, record in best.values()]


def _rosh_review(
    snapshots: list[DecisionSnapshotRecord],
    *,
    winner_team_id: UUID,
) -> dict[str, Any] | None:
    anchor: DecisionSnapshotRecord | None = None
    side_identity: dict[str, Any] | None = None
    curve: dict[str, Any] | None = None
    for snapshot in snapshots:
        payload = snapshot.canonical_payload
        identity = payload.get("identity") if isinstance(payload, dict) else None
        draft = payload.get("draft") if isinstance(payload, dict) else None
        side = identity.get("side_identity") if isinstance(identity, dict) else None
        candidate_curve = draft.get("curve") if isinstance(draft, dict) else None
        points = candidate_curve.get("points") if isinstance(candidate_curve, dict) else None
        if (
            isinstance(side, dict)
            and side.get("status") == "RESOLVED"
            and isinstance(side.get("radiant_team_id"), str)
            and isinstance(side.get("dire_team_id"), str)
            and isinstance(candidate_curve, dict)
            and isinstance(points, list)
            and points
        ):
            anchor = snapshot
            side_identity = side
            curve = candidate_curve
            break
    if anchor is None or side_identity is None or curve is None:
        return None

    points = curve.get("points")
    if not isinstance(points, list):
        return None
    review_points = []
    reference = None
    for minute in ROSH_REVIEW_MINUTES:
        point = _curve_point(points, minute)
        pure = _number(point.get("pure_radiant_edge")) if point is not None else None
        adjusted = _number(point.get("adjusted_radiant_edge")) if point is not None else None
        review_point = {
            "minute": minute,
            "pure": _rosh_edge_payload(pure, side_identity, winner_team_id),
            "adjusted": _rosh_edge_payload(adjusted, side_identity, winner_team_id),
        }
        review_points.append(review_point)
        if minute == ROSH_REFERENCE_MINUTE and point is not None:
            reference = review_point
    return {
        "snapshot_id": str(anchor.id),
        "decision_at": anchor.decision_at,
        "reference_minute": ROSH_REFERENCE_MINUTE,
        "model_version": curve.get("model_version"),
        "data_version": curve.get("data_version"),
        "radiant_team_id": side_identity["radiant_team_id"],
        "dire_team_id": side_identity["dire_team_id"],
        "points": review_points,
        "reference": reference,
    }


def _curve_point(points: list[Any], minute: int) -> dict[str, Any] | None:
    return next(
        (
            item
            for item in points
            if isinstance(item, dict) and _number(item.get("minute")) == float(minute)
        ),
        None,
    )


def _rosh_edge_payload(
    edge: float | None,
    side_identity: dict[str, Any],
    winner_team_id: UUID,
) -> dict[str, Any]:
    favored_team_id = None
    if edge is not None and abs(edge) >= _ROSH_EVEN_EPSILON:
        favored_team_id = (
            side_identity.get("radiant_team_id") if edge > 0 else side_identity.get("dire_team_id")
        )
    return {
        "edge_pp": edge,
        "favored_team_id": favored_team_id,
        "correct": (
            favored_team_id == str(winner_team_id) if isinstance(favored_team_id, str) else None
        ),
    }


def _ai_groups(
    records: list[AiDecisionRecord],
    *,
    evaluation_by_decision: dict[UUID, DecisionEvaluationRecord],
    snapshot_by_id: dict[UUID, DecisionSnapshotRecord],
) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    for record in records:
        key = (record.provider, record.model)
        group = groups.setdefault(
            key,
            {
                "provider": record.provider,
                "model": record.model,
                "rounds": 0,
                "buy_decisions": 0,
                "settled_buy_decisions": 0,
                "correct_buy_decisions": 0,
                "brier_values": [],
                "log_loss_values": [],
                "unit_pnl": 0.0,
                "unit_bets": 0,
                "latest_key": None,
                "latest": None,
            },
        )
        group["rounds"] += 1
        decision = record.normalized_response or {}
        action = decision.get("action")
        evaluation = evaluation_by_decision.get(record.id)
        if action in {"BUY_A", "BUY_B"}:
            group["buy_decisions"] += 1
            if evaluation is not None and evaluation.result_correct is not None:
                group["settled_buy_decisions"] += 1
                if evaluation.result_correct:
                    group["correct_buy_decisions"] += 1
        if evaluation is not None:
            if evaluation.brier_score is not None:
                group["brier_values"].append(float(evaluation.brier_score))
            if evaluation.log_loss is not None:
                group["log_loss_values"].append(float(evaluation.log_loss))
            if evaluation.unit_pnl is not None:
                group["unit_pnl"] += float(evaluation.unit_pnl)
                group["unit_bets"] += 1
        snapshot = snapshot_by_id.get(record.snapshot_id)
        decision_at = snapshot.decision_at if snapshot is not None else record.request_started_at
        latest_key = (decision_at, record.request_started_at)
        if group["latest_key"] is None or latest_key > group["latest_key"]:
            group["latest_key"] = latest_key
            group["latest"] = {
                "snapshot_id": str(record.snapshot_id),
                "decision_at": decision_at,
                "action": action,
                "fair_probability_a": _number(decision.get("fair_probability_a")),
                "confidence": _number(decision.get("confidence")),
                "market_assessment": decision.get("market_assessment"),
            }

    payloads: list[dict[str, Any]] = []
    for group in groups.values():
        settled = group["settled_buy_decisions"]
        unit_bets = group["unit_bets"]
        payloads.append(
            {
                "provider": group["provider"],
                "model": group["model"],
                "rounds": group["rounds"],
                "buy_decisions": group["buy_decisions"],
                "settled_buy_decisions": settled,
                "correct_buy_decisions": group["correct_buy_decisions"],
                "buy_accuracy": group["correct_buy_decisions"] / settled if settled else None,
                "average_brier": mean(group["brier_values"]) if group["brier_values"] else None,
                "average_log_loss": (
                    mean(group["log_loss_values"]) if group["log_loss_values"] else None
                ),
                "unit_pnl": round(group["unit_pnl"], 4) if unit_bets else None,
                "unit_bets": unit_bets,
                "unit_roi": group["unit_pnl"] / unit_bets if unit_bets else None,
                "latest": group["latest"],
            }
        )
    return sorted(payloads, key=lambda item: (item["provider"], item["model"]))


def _odds_review(
    snapshots: list[DecisionSnapshotRecord],
    *,
    closings: list[DecisionFutureOdds],
    ai_min_game_time_seconds: int = 600,
) -> dict[str, Any] | None:
    pairs = [
        pair
        for snapshot in snapshots
        if (
            pair := _snapshot_market_pair(
                snapshot,
                min_game_time_seconds=ai_min_game_time_seconds,
            )
        )
        is not None
    ]
    if not pairs:
        return None
    first = pairs[0]
    latest = pairs[-1]
    captured = [
        item
        for item in closings
        if item.odds_a is not None
        and item.odds_b is not None
        and item.odds_a > 1
        and item.odds_b > 1
        and item.status == "CAPTURED"
        and (item.observed_at is not None or item.triggered_at is not None)
    ]
    if captured:
        closing = max(
            captured,
            key=lambda item: item.observed_at or item.triggered_at,
        )
        end = _odds_pair_payload(
            float(closing.odds_a),
            float(closing.odds_b),
            observed_at=closing.observed_at or closing.triggered_at,
        )
        end_kind = "CLOSING"
    else:
        end = latest
        end_kind = "LATEST_DECISION"
    return {
        "start": first,
        "end": end,
        "end_kind": end_kind,
        "team_a_fair_probability_change_pp": (
            round((end["fair_probability_a"] - first["fair_probability_a"]) * 100.0, 3)
            if end.get("fair_probability_a") is not None
            and first.get("fair_probability_a") is not None
            else None
        ),
    }


def _snapshot_market_pair(
    snapshot: DecisionSnapshotRecord,
    *,
    min_game_time_seconds: int = 600,
) -> dict[str, Any] | None:
    payload = snapshot.canonical_payload
    identity = payload.get("identity") if isinstance(payload, dict) else None
    market = payload.get("market") if isinstance(payload, dict) else None
    snapshot_quality = payload.get("quality") if isinstance(payload, dict) else None
    market_quality = market.get("quality") if isinstance(market, dict) else None
    if (
        not isinstance(identity, dict)
        or not isinstance(market, dict)
        or not isinstance(snapshot_quality, dict)
        or snapshot_quality.get("eligible") is not True
        or not isinstance(market_quality, dict)
        or market_quality.get("eligible") is not True
        or not ai_record_is_game_time_eligible(
            payload,
            decision_at=snapshot.decision_at,
            min_game_time_seconds=min_game_time_seconds,
        )
    ):
        return None
    team_a = identity.get("team_a")
    team_b = identity.get("team_b")
    team_a_id = team_a.get("id") if isinstance(team_a, dict) else None
    team_b_id = team_b.get("id") if isinstance(team_b, dict) else None
    observations = market.get("observations")
    if (
        not isinstance(team_a_id, str)
        or not isinstance(team_b_id, str)
        or not isinstance(observations, list)
    ):
        return None
    by_team = {
        item.get("selection_team_id"): item
        for item in observations
        if isinstance(item, dict) and isinstance(item.get("selection_team_id"), str)
    }
    leg_a = by_team.get(team_a_id)
    leg_b = by_team.get(team_b_id)
    if not isinstance(leg_a, dict) or not isinstance(leg_b, dict):
        return None
    odds_a = _number(leg_a.get("price"))
    odds_b = _number(leg_b.get("price"))
    if odds_a is None or odds_b is None or odds_a <= 1.0 or odds_b <= 1.0:
        return None
    return _odds_pair_payload(odds_a, odds_b, observed_at=snapshot.decision_at)


def _odds_pair_payload(odds_a: float, odds_b: float, *, observed_at: Any) -> dict[str, Any]:
    fair_a = fair_b = None
    try:
        fair_a, fair_b, _ = remove_vig(odds_a, odds_b)
    except TypeError, ValueError, ZeroDivisionError:
        pass
    return {
        "odds_a": odds_a,
        "odds_b": odds_b,
        "fair_probability_a": fair_a,
        "fair_probability_b": fair_b,
        "observed_at": observed_at,
    }


def _review_summary(rows: list[dict[str, Any]], *, ai: list[dict[str, Any]]) -> dict[str, Any]:
    pure = _rosh_accuracy(rows, "pure")
    adjusted = _rosh_accuracy(rows, "adjusted")
    odds_eligible = [item for item in rows if item.get("odds") is not None]
    closing_count = sum(
        item["odds"].get("end_kind") == "CLOSING"
        for item in odds_eligible
        if isinstance(item.get("odds"), dict)
    )
    return {
        "settled_maps": len(rows),
        "rosh": {
            "reference_minute": ROSH_REFERENCE_MINUTE,
            "pure": pure,
            "adjusted": adjusted,
        },
        "ai": ai,
        "odds": {
            "eligible_maps": len(odds_eligible),
            "closing_captured": closing_count,
            "closing_coverage": closing_count / len(odds_eligible) if odds_eligible else None,
        },
    }


def _rosh_accuracy(rows: list[dict[str, Any]], kind: str) -> dict[str, Any]:
    outcomes: list[bool] = []
    for row in rows:
        rosh = row.get("rosh")
        reference = rosh.get("reference") if isinstance(rosh, dict) else None
        value = reference.get(kind) if isinstance(reference, dict) else None
        correct = value.get("correct") if isinstance(value, dict) else None
        if isinstance(correct, bool):
            outcomes.append(correct)
    correct_count = sum(outcomes)
    return {
        "evaluated": len(outcomes),
        "correct": correct_count,
        "accuracy": correct_count / len(outcomes) if outcomes else None,
    }


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None
