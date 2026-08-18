from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models import (
    AiDecisionRecord,
    CanonicalEvent,
    CanonicalMap,
    CanonicalSeries,
    CanonicalTeam,
    DecisionEvaluationRecord,
    DecisionSnapshotRecord,
    DltvLiveObservationRecord,
    DraftMinuteCurveRecord,
    DraftSnapshotRecord,
    MapResultRecord,
    OddsObservationRecord,
    ProviderMatchMapping,
)

REPORT_VERSION = "decision-readiness-v1"
DEFAULT_LOOKBACK_HOURS = 24 * 7
MAX_LOOKBACK_HOURS = 24 * 30
MAX_SERIES = 500

STAGES: tuple[tuple[str, str], ...] = (
    ("scheduled", "SCHEDULED"),
    ("raybet_linked", "RAYBET_LINKED"),
    ("market_ready", "MARKET_READY"),
    ("map_identity", "MAP_IDENTITY"),
    ("live_ready", "LIVE_READY"),
    ("snapshot_ready", "SNAPSHOT_READY"),
    ("ai_decision", "AI_DECISION"),
    ("result_ready", "RESULT_READY"),
    ("evaluated", "EVALUATED"),
)


class DecisionReadinessService:
    """Read-only shadow-validation funnel over existing production records.

    The report deliberately derives facts from persisted evidence instead of
    inventing lifecycle state. Stage counts are cumulative (a true funnel),
    while each series also exposes independent evidence flags so a later fact
    never hides an earlier pipeline gap.
    """

    async def build_report(
        self,
        session: AsyncSession,
        *,
        now: datetime | None = None,
        lookback_hours: int = DEFAULT_LOOKBACK_HOURS,
        limit: int = MAX_SERIES,
    ) -> dict[str, Any]:
        generated_at = now or datetime.now(UTC)
        safe_lookback = min(max(int(lookback_hours), 1), MAX_LOOKBACK_HOURS)
        safe_limit = min(max(int(limit), 1), MAX_SERIES)
        window_start = generated_at - timedelta(hours=safe_lookback)

        team_a = aliased(CanonicalTeam)
        team_b = aliased(CanonicalTeam)
        liquipedia_backed = (
            select(ProviderMatchMapping.id)
            .where(
                ProviderMatchMapping.provider == "liquipedia",
                ProviderMatchMapping.canonical_series_id == CanonicalSeries.id,
            )
            .exists()
        )
        series_rows = list(
            (
                await session.execute(
                    select(
                        CanonicalSeries,
                        CanonicalEvent.name.label("event_name"),
                        team_a.name.label("team_a_name"),
                        team_b.name.label("team_b_name"),
                    )
                    .outerjoin(CanonicalEvent, CanonicalEvent.id == CanonicalSeries.event_id)
                    .join(team_a, team_a.id == CanonicalSeries.team_a_id)
                    .join(team_b, team_b.id == CanonicalSeries.team_b_id)
                    .where(
                        liquipedia_backed,
                        CanonicalSeries.scheduled_at.is_not(None),
                        CanonicalSeries.scheduled_at >= window_start,
                        CanonicalSeries.scheduled_at <= generated_at,
                    )
                    .order_by(CanonicalSeries.scheduled_at.desc(), CanonicalSeries.id)
                    .limit(safe_limit)
                )
            ).all()
        )
        if not series_rows:
            return _empty_report(
                generated_at=generated_at,
                window_start=window_start,
                lookback_hours=safe_lookback,
            )

        series_ids = {row.CanonicalSeries.id for row in series_rows}
        raybet_series_ids = set(
            (
                await session.scalars(
                    select(ProviderMatchMapping.canonical_series_id)
                    .where(
                        ProviderMatchMapping.provider == "raybet",
                        ProviderMatchMapping.canonical_series_id.in_(series_ids),
                    )
                    .distinct()
                )
            ).all()
        )
        market_series_ids = set(
            (
                await session.scalars(
                    select(OddsObservationRecord.canonical_series_id)
                    .where(OddsObservationRecord.canonical_series_id.in_(series_ids))
                    .distinct()
                )
            ).all()
        )

        map_rows = list(
            (
                await session.execute(
                    select(CanonicalMap.id, CanonicalMap.series_id).where(
                        CanonicalMap.series_id.in_(series_ids)
                    )
                )
            ).all()
        )
        maps_by_series: dict[UUID, set[UUID]] = defaultdict(set)
        map_to_series: dict[UUID, UUID] = {}
        for map_id, series_id in map_rows:
            if series_id is None:
                continue
            maps_by_series[series_id].add(map_id)
            map_to_series[map_id] = series_id
        map_ids = set(map_to_series)

        live_map_ids: set[UUID] = set()
        snapshot_rows: list[tuple[UUID, UUID | None]] = []
        result_map_ids: set[UUID] = set()
        draft_present_map_ids: set[UUID] = set()
        draft_complete_map_ids: set[UUID] = set()
        draft_curve_map_ids: set[UUID] = set()
        if map_ids:
            live_map_ids = set(
                (
                    await session.scalars(
                        select(DltvLiveObservationRecord.canonical_map_id)
                        .where(DltvLiveObservationRecord.canonical_map_id.in_(map_ids))
                        .distinct()
                    )
                ).all()
            )
            snapshot_rows = list(
                (
                    await session.execute(
                        select(
                            DecisionSnapshotRecord.id, DecisionSnapshotRecord.canonical_map_id
                        ).where(DecisionSnapshotRecord.canonical_map_id.in_(map_ids))
                    )
                ).all()
            )
            result_map_ids = set(
                (
                    await session.scalars(
                        select(MapResultRecord.canonical_map_id)
                        .where(MapResultRecord.canonical_map_id.in_(map_ids))
                        .distinct()
                    )
                ).all()
            )
            draft_rows = list(
                (
                    await session.execute(
                        select(
                            DraftSnapshotRecord.id,
                            DraftSnapshotRecord.canonical_map_id,
                            DraftSnapshotRecord.complete,
                        ).where(DraftSnapshotRecord.canonical_map_id.in_(map_ids))
                    )
                ).all()
            )
            draft_present_map_ids = {canonical_map_id for _, canonical_map_id, _ in draft_rows}
            draft_complete_map_ids = {
                canonical_map_id for _, canonical_map_id, complete in draft_rows if complete
            }
            draft_curve_map_ids = set(
                (
                    await session.scalars(
                        select(DraftSnapshotRecord.canonical_map_id)
                        .join(
                            DraftMinuteCurveRecord,
                            DraftMinuteCurveRecord.draft_snapshot_id == DraftSnapshotRecord.id,
                        )
                        .where(DraftSnapshotRecord.canonical_map_id.in_(map_ids))
                        .distinct()
                    )
                ).all()
            )

        snapshots_by_map: dict[UUID, set[UUID]] = defaultdict(set)
        snapshot_to_map: dict[UUID, UUID] = {}
        for snapshot_id, map_id in snapshot_rows:
            if map_id is None:
                continue
            snapshots_by_map[map_id].add(snapshot_id)
            snapshot_to_map[snapshot_id] = map_id
        snapshot_ids = set(snapshot_to_map)

        successful_snapshot_ids: set[UUID] = set()
        ai_statuses_by_snapshot: dict[UUID, Counter[str]] = defaultdict(Counter)
        evaluated_snapshot_ids: set[UUID] = set()
        if snapshot_ids:
            ai_rows = list(
                (
                    await session.execute(
                        select(
                            AiDecisionRecord.id,
                            AiDecisionRecord.snapshot_id,
                            AiDecisionRecord.parse_status,
                        ).where(AiDecisionRecord.snapshot_id.in_(snapshot_ids))
                    )
                ).all()
            )
            decision_to_snapshot: dict[UUID, UUID] = {}
            for decision_id, snapshot_id, parse_status in ai_rows:
                decision_to_snapshot[decision_id] = snapshot_id
                normalized_status = (parse_status or "UNKNOWN").upper()
                ai_statuses_by_snapshot[snapshot_id][normalized_status] += 1
                if normalized_status == "SUCCESS":
                    successful_snapshot_ids.add(snapshot_id)
            decision_ids = set(decision_to_snapshot)
            if decision_ids:
                evaluated_decision_ids = set(
                    (
                        await session.scalars(
                            select(DecisionEvaluationRecord.ai_decision_id)
                            .where(DecisionEvaluationRecord.ai_decision_id.in_(decision_ids))
                            .distinct()
                        )
                    ).all()
                )
                evaluated_snapshot_ids = {
                    decision_to_snapshot[decision_id]
                    for decision_id in evaluated_decision_ids
                    if decision_id in decision_to_snapshot
                }

        stage_counts: Counter[str] = Counter()
        blocker_counts: Counter[tuple[str, str]] = Counter()
        series_payload: list[dict[str, Any]] = []
        for row in series_rows:
            series = row.CanonicalSeries
            series_map_ids = maps_by_series.get(series.id, set())
            series_snapshot_ids = {
                snapshot_id
                for map_id in series_map_ids
                for snapshot_id in snapshots_by_map.get(map_id, set())
            }
            status_counts: Counter[str] = Counter()
            for snapshot_id in series_snapshot_ids:
                status_counts.update(ai_statuses_by_snapshot.get(snapshot_id, Counter()))

            facts = {
                "scheduled": True,
                "raybet_linked": series.id in raybet_series_ids,
                "market_ready": series.id in market_series_ids,
                "map_identity": bool(series_map_ids),
                "live_ready": bool(series_map_ids & live_map_ids),
                "snapshot_ready": bool(series_snapshot_ids),
                "ai_decision": bool(series_snapshot_ids & successful_snapshot_ids),
                "result_ready": bool(series_map_ids & result_map_ids),
                "evaluated": bool(series_snapshot_ids & evaluated_snapshot_ids),
            }
            cumulative: dict[str, bool] = {}
            running = True
            for stage_key, _label in STAGES:
                running = running and facts[stage_key]
                cumulative[stage_key] = running
                if running:
                    stage_counts[stage_key] += 1

            current_stage = "NOT_STARTED"
            for stage_key, stage_label in STAGES:
                if cumulative[stage_key]:
                    current_stage = stage_label
                else:
                    break
            blocker = _first_blocker(
                facts=facts,
                series_map_ids=series_map_ids,
                live_map_ids=live_map_ids,
                draft_present_map_ids=draft_present_map_ids,
                draft_complete_map_ids=draft_complete_map_ids,
                draft_curve_map_ids=draft_curve_map_ids,
                ai_statuses=status_counts,
            )
            if blocker is not None:
                blocker_counts[(blocker[0], blocker[1])] += 1

            series_payload.append(
                {
                    "canonical_series_id": str(series.id),
                    "canonical_event_id": str(series.event_id)
                    if series.event_id is not None
                    else None,
                    "event_name": row.event_name,
                    "scheduled_at": series.scheduled_at,
                    "team_a": {"id": str(series.team_a_id), "name": row.team_a_name},
                    "team_b": {"id": str(series.team_b_id), "name": row.team_b_name},
                    "best_of": series.best_of,
                    "current_stage": current_stage,
                    "blocker": (
                        {"stage": blocker[0], "reason": blocker[1]} if blocker is not None else None
                    ),
                    "facts": facts,
                    "counts": {
                        "maps": len(series_map_ids),
                        "live_maps": len(series_map_ids & live_map_ids),
                        "snapshots": len(series_snapshot_ids),
                        "successful_decision_snapshots": len(
                            series_snapshot_ids & successful_snapshot_ids
                        ),
                        "result_maps": len(series_map_ids & result_map_ids),
                        "evaluated_snapshots": len(series_snapshot_ids & evaluated_snapshot_ids),
                    },
                    "ai_status_counts": dict(sorted(status_counts.items())),
                }
            )

        total = len(series_payload)
        stages = []
        previous_count = total
        for stage_key, stage_label in STAGES:
            count = stage_counts[stage_key]
            stages.append(
                {
                    "key": stage_key,
                    "label": stage_label,
                    "count": count,
                    "rate": count / total if total else None,
                    "drop_count": previous_count - count,
                }
            )
            previous_count = count

        failure_reasons = [
            {"stage": stage, "reason": reason, "count": count, "rate": count / total}
            for (stage, reason), count in sorted(
                blocker_counts.items(),
                key=lambda item: (-item[1], item[0][0], item[0][1]),
            )
        ]
        return {
            "report_version": REPORT_VERSION,
            "generated_at": generated_at,
            "window": {
                "from": window_start,
                "to": generated_at,
                "lookback_hours": safe_lookback,
                "future_series_included": False,
            },
            "scope": {
                "source": "LIQUIPEDIA_BACKED_CANONICAL_SERIES",
                "series_count": total,
                "series_limit": safe_limit,
            },
            "stages": stages,
            "failure_reasons": failure_reasons,
            "series": series_payload,
        }


def _first_blocker(
    *,
    facts: dict[str, bool],
    series_map_ids: set[UUID],
    live_map_ids: set[UUID],
    draft_present_map_ids: set[UUID],
    draft_complete_map_ids: set[UUID],
    draft_curve_map_ids: set[UUID],
    ai_statuses: Counter[str],
) -> tuple[str, str] | None:
    if not facts["raybet_linked"]:
        return "raybet_linked", "RAYBET_IDENTITY_MISSING"
    if not facts["market_ready"]:
        return "market_ready", "MARKET_OBSERVATION_MISSING"
    if not facts["map_identity"]:
        return "map_identity", "CANONICAL_MAP_MISSING"
    if not facts["live_ready"]:
        return "live_ready", "DLTV_LIVE_MISSING"
    if not facts["snapshot_ready"]:
        live_series_maps = series_map_ids & live_map_ids
        if not live_series_maps & draft_present_map_ids:
            return "snapshot_ready", "DRAFT_MISSING"
        if not live_series_maps & draft_complete_map_ids:
            return "snapshot_ready", "DRAFT_INCOMPLETE"
        if not live_series_maps & draft_curve_map_ids:
            return "snapshot_ready", "DRAFT_CURVE_MISSING"
        return "snapshot_ready", "SNAPSHOT_GATE_BLOCKED"
    if not facts["ai_decision"]:
        failed = [(status, count) for status, count in ai_statuses.items() if status != "SUCCESS"]
        if failed:
            status = max(failed, key=lambda item: (item[1], item[0]))[0]
            return "ai_decision", f"AI_{status}"
        return "ai_decision", "AI_DECISION_MISSING"
    if not facts["result_ready"]:
        return "result_ready", "RESULT_MISSING"
    if not facts["evaluated"]:
        return "evaluated", "EVALUATION_MISSING"
    return None


def _empty_report(
    *,
    generated_at: datetime,
    window_start: datetime,
    lookback_hours: int,
) -> dict[str, Any]:
    return {
        "report_version": REPORT_VERSION,
        "generated_at": generated_at,
        "window": {
            "from": window_start,
            "to": generated_at,
            "lookback_hours": lookback_hours,
            "future_series_included": False,
        },
        "scope": {
            "source": "LIQUIPEDIA_BACKED_CANONICAL_SERIES",
            "series_count": 0,
            "series_limit": MAX_SERIES,
        },
        "stages": [
            {"key": key, "label": label, "count": 0, "rate": None, "drop_count": 0}
            for key, label in STAGES
        ],
        "failure_reasons": [],
        "series": [],
    }
