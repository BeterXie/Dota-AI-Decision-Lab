from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.live.freshness import load_live_basic_field_freshness
from app.models import (
    CanonicalMap,
    CanonicalSeries,
    CanonicalTeam,
    LiveSyncEstimateRecord,
    MapResultRecord,
)
from app.providers.dltv.side_identity import (
    MapSideAssignment,
    project_map_sides,
    side_assignment_payload,
)
from app.snapshots.builder import SnapshotBuilder, SnapshotBuildOutcome, _sync_payload
from app.snapshots.gates import GateContext, evaluate_gate


class SideAwareSnapshotBuilder(SnapshotBuilder):
    async def build(
        self,
        session: AsyncSession,
        *,
        canonical_map_id: UUID | None = None,
        canonical_series_id: UUID | None = None,
        decision_at: datetime,
    ) -> SnapshotBuildOutcome:
        if canonical_map_id is None and canonical_series_id is None:
            raise ValueError("canonical map or series is required")
        canonical_map = (
            await session.get(CanonicalMap, canonical_map_id)
            if canonical_map_id is not None
            else None
        )
        if canonical_map_id is not None and canonical_map is None:
            raise ValueError("canonical map does not exist")
        resolved_series_id = (
            canonical_map.series_id if canonical_map is not None else canonical_series_id
        )
        series = await session.get(CanonicalSeries, resolved_series_id)
        if series is None:
            raise ValueError("canonical series does not exist")
        team_a = await session.get(CanonicalTeam, series.team_a_id)
        team_b = await session.get(CanonicalTeam, series.team_b_id)
        series_score = await _series_score(session, series=series, decision_at=decision_at)
        side_assignment = (
            await project_map_sides(
                session,
                canonical_map=canonical_map,
                series=series,
                as_of=decision_at,
            )
            if canonical_map is not None
            else None
        )
        identity = {
            "event_id": str(series.event_id) if series.event_id is not None else None,
            "series_id": str(series.id),
            "map_id": str(canonical_map.id) if canonical_map is not None else None,
            "map_number": canonical_map.map_number if canonical_map is not None else None,
            "valve_match_id": canonical_map.valve_match_id if canonical_map is not None else None,
            "team_a": {
                "id": str(series.team_a_id),
                "name": team_a.name if team_a is not None else None,
            },
            "team_b": {
                "id": str(series.team_b_id),
                "name": team_b.name if team_b is not None else None,
            },
            "series_context": {
                "best_of": series.best_of,
                "scheduled_at": series.scheduled_at,
                "map_number": canonical_map.map_number if canonical_map is not None else None,
                "score_a": series_score[0],
                "score_b": series_score[1],
                "score_knowledge_cutoff": series_score[2],
            },
            "side_identity": (
                side_assignment_payload(side_assignment) if side_assignment is not None else None
            ),
        }
        identity_complete = (
            team_a is not None and team_b is not None and series.team_a_id != series.team_b_id
        )
        (
            market,
            market_age,
            market_pair_valid,
            market_blockers,
            market_warnings,
        ) = await self._load_market(
            session,
            canonical_map_id=canonical_map_id,
            canonical_series_id=series.id,
            expected_team_ids=(series.team_a_id, series.team_b_id),
            decision_at=decision_at,
        )
        if canonical_map_id is None:
            draft, slots, draft_complete = None, [], False
        else:
            draft, slots, draft_complete = await self._load_draft(
                session, canonical_map_id=canonical_map_id, decision_at=decision_at
            )
        history, history_blockers, history_warnings = await self._load_history(
            session,
            series=series,
            slots=slots,
            decision_at=decision_at,
        )
        await _enrich_history(
            session,
            history=history,
            slots=slots,
            history_service=self._history,
            decision_at=decision_at,
        )
        side_resolved = side_assignment is not None and side_assignment.resolved
        if slots:
            if side_resolved:
                _align_history_to_series(history, side_assignment, series)
            else:
                _remove_unassigned_roster_history(history)
                history_blockers = [
                    blocker
                    for blocker in history_blockers
                    if blocker != "ROSTER_IDENTITY_AMBIGUOUS"
                ]
                history_warnings.append("ROSTER_SIDE_IDENTITY_UNRESOLVED")
        effective_draft_complete = draft_complete and side_resolved
        if draft_complete and not side_resolved:
            history_warnings.append(
                side_assignment.blocker
                if side_assignment is not None and side_assignment.blocker is not None
                else "SIDE_IDENTITY_UNRESOLVED"
            )
        live_field_freshness = None
        if canonical_map_id is None:
            live, live_message_age, live_age, live_complete, sync = (
                None,
                None,
                None,
                False,
                None,
            )
        else:
            live, live_message_age, live_age, live_complete = await self._load_live(
                session, canonical_map_id=canonical_map_id, decision_at=decision_at
            )
            if (
                canonical_map is not None
                and canonical_map.valve_match_id is not None
                and live is not None
            ):
                live_field_freshness = await load_live_basic_field_freshness(
                    session,
                    valve_match_id=canonical_map.valve_match_id,
                    decision_at=decision_at,
                    max_age_seconds=self._settings.live_state_max_age_seconds,
                )
                live_age = live_field_freshness.effective_age_seconds
                live["field_freshness"] = live_field_freshness.payload()
            sync = await session.scalar(
                select(LiveSyncEstimateRecord)
                .where(
                    LiveSyncEstimateRecord.canonical_map_id == canonical_map_id,
                    LiveSyncEstimateRecord.calculated_at <= decision_at,
                )
                .order_by(LiveSyncEstimateRecord.calculated_at.desc())
                .limit(1)
            )
        if live is not None and not live_complete:
            history_warnings.append("LIVE_PARTIAL")
        gate = evaluate_gate(
            GateContext(
                identity_complete=identity_complete,
                market_available=market is not None,
                market_pair_valid=market_pair_valid,
                market_blockers=market_blockers,
                market_warnings=market_warnings,
                market_age_seconds=market_age,
                market_max_age_seconds=self._settings.live_market_max_age_seconds,
                draft_available=draft is not None,
                draft_complete=effective_draft_complete,
                historical_future_leak=False,
                historical_blockers=tuple(history_blockers),
                historical_warnings=tuple(history_warnings),
                live_available=live is not None and live_complete,
                live_message_age_seconds=live_message_age,
                live_age_seconds=live_age,
                live_max_age_seconds=self._settings.live_state_max_age_seconds,
                live_sync_status=sync.status if sync is not None else None,
                live_sync_confidence=sync.confidence if sync is not None else None,
            )
        )
        if not gate.eligible:
            return SnapshotBuildOutcome(gate=gate, snapshot=None)
        quality = {
            "eligible": gate.eligible,
            "blockers": list(gate.blockers),
            "warnings": list(gate.warnings),
            "market_age_seconds": market_age,
            "live_message_age_seconds": live_message_age,
            "live_effective_state_age_seconds": live_age,
            "live_field_freshness": (
                live_field_freshness.payload() if live_field_freshness is not None else None
            ),
            "live_sync": _sync_payload(sync),
        }
        snapshot = await self._repository.persist(
            session,
            canonical_map_id=canonical_map_id,
            decision_at=decision_at,
            mode=gate.mode.value,
            identity=identity,
            market=market or {},
            draft=draft if gate.mode.value != "PREMATCH" else None,
            history=history,
            live=live if gate.mode.value.startswith("LIVE_") else None,
            quality=quality,
        )
        return SnapshotBuildOutcome(gate=gate, snapshot=snapshot)


async def _series_score(
    session: AsyncSession,
    *,
    series: CanonicalSeries,
    decision_at: datetime,
) -> tuple[int, int, datetime | None]:
    rows = list(
        (
            await session.scalars(
                select(MapResultRecord)
                .join(CanonicalMap, CanonicalMap.id == MapResultRecord.canonical_map_id)
                .where(
                    CanonicalMap.series_id == series.id,
                    MapResultRecord.basic_first_usable_at <= decision_at,
                    MapResultRecord.winner_team_id.is_not(None),
                )
                .order_by(MapResultRecord.basic_first_usable_at)
            )
        ).all()
    )
    score_a = sum(result.winner_team_id == series.team_a_id for result in rows)
    score_b = sum(result.winner_team_id == series.team_b_id for result in rows)
    cutoff = max((result.basic_first_usable_at for result in rows), default=None)
    return score_a, score_b, cutoff


async def _enrich_history(
    session: AsyncSession,
    *,
    history: dict[str, Any],
    slots: list,
    history_service,
    decision_at: datetime,
) -> None:
    by_side = {
        "radiant": history.get("players_a", []),
        "dire": history.get("players_b", []),
    }
    for slot in slots:
        if slot.canonical_player_id is None or slot.hero_id is None:
            continue
        player_context = await history_service.get_player_payload(
            session,
            slot.canonical_player_id,
            position=slot.position,
            as_of=decision_at,
        )
        hero_context = await history_service.get_player_hero_payload(
            session,
            slot.canonical_player_id,
            hero_id=slot.hero_id,
            position=slot.position,
            as_of=decision_at,
        )
        player_id = str(slot.canonical_player_id)
        target = next(
            (
                item
                for item in by_side.get(slot.side, [])
                if item.get("canonical_player_id") == player_id
            ),
            None,
        )
        if target is None:
            continue
        target.update(
            {
                "recent_5": player_context.get("recent_5"),
                "recent_10": player_context.get("recent_10"),
                "recent_20": player_context.get("recent_20"),
                "player_sample_size": player_context.get("sample_size"),
                "position_source": slot.source,
                "position_confidence": slot.confidence,
                "player_hero": hero_context,
            }
        )


def _align_history_to_series(
    history: dict[str, Any], assignment: MapSideAssignment, series: CanonicalSeries
) -> None:
    if assignment.radiant_team_id == series.team_a_id:
        return
    if assignment.radiant_team_id != series.team_b_id:
        raise ValueError("resolved side assignment does not match canonical series")
    history["players_a"], history["players_b"] = history["players_b"], history["players_a"]
    team_a = history.get("team_a")
    team_b = history.get("team_b")
    if isinstance(team_a, dict) and isinstance(team_b, dict):
        team_a_strength = team_a.get("current_roster_strength")
        team_b_strength = team_b.get("current_roster_strength")
        team_a["current_roster_strength"] = team_b_strength
        team_b["current_roster_strength"] = team_a_strength


def _remove_unassigned_roster_history(history: dict[str, Any]) -> None:
    history["players_a"] = []
    history["players_b"] = []
    team_a = history.get("team_a")
    team_b = history.get("team_b")
    if isinstance(team_a, dict):
        team_a["current_roster_strength"] = None
    if isinstance(team_b, dict):
        team_b["current_roster_strength"] = None
    coverage = history.get("coverage")
    if isinstance(coverage, dict):
        coverage["roster_player_count"] = 0
        coverage["player_form_ready_count"] = 0
        coverage["player_hero_ready_count"] = 0
        cutoffs = [
            team.get("knowledge_cutoff")
            for team in (team_a, team_b)
            if isinstance(team, dict) and team.get("knowledge_cutoff") is not None
        ]
        coverage["earliest_knowledge_cutoff"] = min(cutoffs) if cutoffs else None
        coverage["latest_knowledge_cutoff"] = max(cutoffs) if cutoffs else None
