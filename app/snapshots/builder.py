from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from statistics import mean
from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.domain.snapshot import DecisionSnapshot, GateResult
from app.history.service import HistoricalIntelligenceService
from app.live.anchor import dltv_broadcast_start, picks_ended_anchor
from app.live.freshness import load_live_basic_field_freshness
from app.market.fair_probability import remove_vig
from app.market.pairing import MarketPairLeg, evaluate_market_pair
from app.models import (
    CanonicalMap,
    CanonicalSeries,
    CanonicalTeam,
    DltvLiveObservationRecord,
    DraftMinuteCurveRecord,
    DraftSlotRecord,
    DraftSnapshotRecord,
    LiveSyncEstimateRecord,
    MapResultRecord,
    OddsObservationRecord,
    ProviderRawEvent,
)
from app.providers.dltv.parser import parse_live_enrichment
from app.providers.dltv.side_identity import (
    MapSideAssignment,
    project_map_sides,
    side_assignment_payload,
)
from app.snapshots.gates import GateContext, evaluate_gate
from app.snapshots.repository import SnapshotRepository
from app.time import elapsed_seconds, ensure_utc


@dataclass(frozen=True)
class SnapshotBuildOutcome:
    gate: GateResult
    snapshot: DecisionSnapshot | None


class BaseSnapshotBuilder:
    def __init__(
        self,
        *,
        settings: Settings,
        history: HistoricalIntelligenceService,
        repository: SnapshotRepository,
    ) -> None:
        self._settings = settings
        self._history = history
        self._repository = repository

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
        identity = {
            "event_id": str(series.event_id) if series.event_id is not None else None,
            "series_id": str(series.id),
            "map_id": str(canonical_map.id) if canonical_map is not None else None,
            "map_number": canonical_map.map_number if canonical_map is not None else None,
            "valve_match_id": (canonical_map.valve_match_id if canonical_map is not None else None),
            "team_a": {
                "id": str(series.team_a_id),
                "name": team_a.name if team_a is not None else None,
            },
            "team_b": {
                "id": str(series.team_b_id),
                "name": team_b.name if team_b is not None else None,
            },
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
                draft_complete=draft_complete,
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

    async def _load_market(
        self,
        session: AsyncSession,
        *,
        canonical_map_id: UUID | None,
        canonical_series_id: UUID,
        expected_team_ids: tuple[UUID, UUID],
        decision_at: datetime,
    ) -> tuple[
        dict[str, Any] | None,
        float | None,
        bool,
        tuple[str, ...],
        tuple[str, ...],
    ]:
        map_number = (
            await session.scalar(
                select(CanonicalMap.map_number).where(CanonicalMap.id == canonical_map_id)
            )
            if canonical_map_id is not None
            else None
        )
        best_of = await session.scalar(
            select(CanonicalSeries.best_of).where(CanonicalSeries.id == canonical_series_id)
        )
        criteria = [
            or_(
                (
                    OddsObservationRecord.canonical_map_id == canonical_map_id
                    if canonical_map_id is not None
                    else False
                ),
                OddsObservationRecord.canonical_series_id == canonical_series_id,
            ),
            OddsObservationRecord.received_at <= decision_at,
            OddsObservationRecord.market_type == "Winner",
        ]
        if canonical_map_id is not None:
            criteria.append(
                OddsObservationRecord.match_stage.in_(
                    _map_market_stages(map_number, best_of=best_of)
                )
            )
        latest_times = (
            select(
                OddsObservationRecord.odds_id,
                func.max(OddsObservationRecord.received_at).label("latest_received_at"),
            )
            .where(*criteria)
            .group_by(OddsObservationRecord.odds_id)
            .subquery()
        )
        records = list(
            (
                await session.scalars(
                    select(OddsObservationRecord).join(
                        latest_times,
                        and_(
                            OddsObservationRecord.odds_id == latest_times.c.odds_id,
                            OddsObservationRecord.received_at == latest_times.c.latest_received_at,
                        ),
                    )
                )
            ).all()
        )
        latest_by_odds_id: dict[int, OddsObservationRecord] = {}
        for record in records:
            latest_by_odds_id.setdefault(record.odds_id, record)
        grouped: dict[tuple[int, str | None, str | None], list[OddsObservationRecord]] = {}
        for record in latest_by_odds_id.values():
            key = (record.provider_match_id, record.market_type, record.match_stage)
            grouped.setdefault(key, []).append(record)
        if not grouped:
            return None, None, False, (), ()
        evaluated = []
        for (_provider_match_id, _market_type, match_stage), items in grouped.items():
            quality = evaluate_market_pair(
                tuple(_market_pair_leg(item) for item in items),
                expected_series_id=canonical_series_id,
                # The deciding-map fallback uses the series-scoped "final"
                # market whose observations carry no map identity; map checks
                # are skipped for that stage by design.
                expected_map_id=None if match_stage == "final" else canonical_map_id,
                expected_team_ids=frozenset(expected_team_ids),
                decision_at=decision_at,
                max_age_seconds=self._settings.live_market_max_age_seconds,
                max_pair_skew_seconds=self._settings.market_max_pair_skew_seconds,
            )
            evaluated.append((items, quality))
        eligible = [candidate for candidate in evaluated if candidate[1].eligible]
        selected, quality = max(
            eligible or evaluated,
            key=lambda candidate: max(item.received_at for item in candidate[0]),
        )
        team_order = {team_id: index for index, team_id in enumerate(expected_team_ids)}
        selected.sort(key=lambda item: (team_order.get(item.selection_team_id, 2), item.odds_id))
        fair_probabilities: tuple[float | None, float | None] = (None, None)
        overround = None
        if quality.eligible:
            fair_a, fair_b, implied_total = remove_vig(
                float(selected[0].price), float(selected[1].price)
            )
            fair_probabilities = (fair_a, fair_b)
            overround = implied_total - 1.0
        observations = [
            _market_observation(item, fair_probability)
            for item, fair_probability in zip(selected, fair_probabilities, strict=False)
        ]
        age = max(elapsed_seconds(decision_at, item.received_at) for item in selected)
        return (
            {
                "provider": "raybet",
                "provider_match_id": selected[0].provider_match_id,
                "market_type": selected[0].market_type,
                "match_stage": selected[0].match_stage,
                "overround": overround,
                "quality": quality.model_dump(mode="json"),
                "observations": observations,
            },
            age,
            quality.eligible,
            quality.blockers,
            quality.warnings,
        )

    async def _load_draft(
        self,
        session: AsyncSession,
        *,
        canonical_map_id: UUID,
        decision_at: datetime,
    ) -> tuple[dict[str, Any] | None, list[DraftSlotRecord], bool]:
        snapshot = await session.scalar(
            select(DraftSnapshotRecord)
            .where(
                DraftSnapshotRecord.canonical_map_id == canonical_map_id,
                DraftSnapshotRecord.observed_at <= decision_at,
                DraftSnapshotRecord.statistics_cutoff <= decision_at,
            )
            .order_by(DraftSnapshotRecord.observed_at.desc())
            .limit(1)
        )
        if snapshot is None:
            return None, [], False
        slots = list(
            (
                await session.scalars(
                    select(DraftSlotRecord).where(DraftSlotRecord.draft_snapshot_id == snapshot.id)
                )
            ).all()
        )
        slots.sort(key=lambda slot: (0 if slot.side == "radiant" else 1, slot.position))
        curve = await session.scalar(
            select(DraftMinuteCurveRecord)
            .where(
                DraftMinuteCurveRecord.draft_snapshot_id == snapshot.id,
                DraftMinuteCurveRecord.statistics_cutoff <= decision_at,
                DraftMinuteCurveRecord.calculated_at <= decision_at,
            )
            .order_by(DraftMinuteCurveRecord.calculated_at.desc())
            .limit(1)
        )
        payload = {
            "draft_snapshot_id": str(snapshot.id),
            "complete": snapshot.complete,
            "blockers": snapshot.blockers,
            "warnings": snapshot.warnings,
            "statistics_cutoff": snapshot.statistics_cutoff,
            "slots": [
                {
                    "side": slot.side,
                    "position": slot.position,
                    "account_id": slot.account_id,
                    "canonical_player_id": (
                        str(slot.canonical_player_id)
                        if slot.canonical_player_id is not None
                        else None
                    ),
                    "hero_id": slot.hero_id,
                    "confidence": slot.confidence,
                }
                for slot in slots
            ],
            "curve": (
                {
                    "points": curve.points,
                    "derived_features": curve.derived_features,
                    "statistics_cutoff": curve.statistics_cutoff,
                    "model_version": curve.model_version,
                    "data_version": curve.data_version,
                }
                if curve is not None
                else None
            ),
        }
        complete = snapshot.complete and len(slots) == 10 and curve is not None
        return payload, slots, complete

    async def _load_history(
        self,
        session: AsyncSession,
        *,
        series: CanonicalSeries,
        slots: list[DraftSlotRecord],
        decision_at: datetime,
    ) -> tuple[dict[str, Any], list[str], list[str]]:
        team_a = await self._history.get_team_payload(session, series.team_a_id, as_of=decision_at)
        team_b = await self._history.get_team_payload(session, series.team_b_id, as_of=decision_at)
        blockers: list[str] = []
        warnings: list[str] = []
        if team_a["base_rating"] is None or team_b["base_rating"] is None:
            warnings.append("HISTORICAL_TEAM_STRENGTH_MISSING")

        players_a: list[dict[str, Any]] = []
        players_b: list[dict[str, Any]] = []
        for slot in slots:
            target = players_a if slot.side == "radiant" else players_b
            if slot.canonical_player_id is None:
                blockers.append("ROSTER_IDENTITY_AMBIGUOUS")
                continue
            player = await self._history.get_player_payload(
                session,
                slot.canonical_player_id,
                position=slot.position,
                as_of=decision_at,
            )
            player_hero = await self._history.get_player_hero_payload(
                session,
                slot.canonical_player_id,
                hero_id=slot.hero_id,
                position=slot.position,
                as_of=decision_at,
            )
            target.append(
                {
                    "canonical_player_id": str(slot.canonical_player_id),
                    "account_id": slot.account_id,
                    "position": slot.position,
                    "base_strength": player["base_strength"],
                    "recent_form": player["recent_form"],
                    "recent_form_confidence": player["confidence"],
                    "current_hero": slot.hero_id,
                    "player_hero_strength": player_hero["adjusted_strength"],
                    "player_hero_sample": player_hero.get("historical_maps"),
                    "player_hero_confidence": player_hero["confidence"],
                    "position_fit": player_hero.get("position_fit"),
                    "knowledge_cutoff": _latest_cutoff(
                        player["knowledge_cutoff"], player_hero["knowledge_cutoff"]
                    ),
                }
            )
        team_a["current_roster_strength"] = _roster_strength(players_a)
        team_b["current_roster_strength"] = _roster_strength(players_b)
        cutoffs = [
            value
            for value in (
                team_a.get("knowledge_cutoff"),
                team_b.get("knowledge_cutoff"),
                *(item.get("knowledge_cutoff") for item in players_a),
                *(item.get("knowledge_cutoff") for item in players_b),
            )
            if value is not None
        ]
        return (
            {
                "team_a": team_a,
                "team_b": team_b,
                "players_a": players_a,
                "players_b": players_b,
                "coverage": {
                    "team_strength_ready_count": sum(
                        item.get("base_rating") is not None for item in (team_a, team_b)
                    ),
                    "roster_player_count": len(players_a) + len(players_b),
                    "player_form_ready_count": sum(
                        item.get("base_strength") is not None or item.get("recent_form") is not None
                        for item in (*players_a, *players_b)
                    ),
                    "player_hero_ready_count": sum(
                        item.get("player_hero_strength") is not None
                        for item in (*players_a, *players_b)
                    ),
                    "earliest_knowledge_cutoff": min(cutoffs) if cutoffs else None,
                    "latest_knowledge_cutoff": max(cutoffs) if cutoffs else None,
                },
            },
            blockers,
            warnings,
        )

    async def _load_live(
        self,
        session: AsyncSession,
        *,
        canonical_map_id: UUID,
        decision_at: datetime,
    ) -> tuple[dict[str, Any] | None, float | None, float | None, bool]:
        record = await session.scalar(
            select(DltvLiveObservationRecord)
            .where(
                DltvLiveObservationRecord.canonical_map_id == canonical_map_id,
                DltvLiveObservationRecord.received_at <= decision_at,
            )
            .order_by(DltvLiveObservationRecord.received_at.desc())
            .limit(1)
        )
        if record is None:
            return None, None, None, False
        latest_message_at = await session.scalar(
            select(ProviderRawEvent.received_at)
            .where(
                ProviderRawEvent.provider == "dltv",
                ProviderRawEvent.provider_key == f"__nd2_match_{record.valve_match_id}",
                ProviderRawEvent.received_at <= decision_at,
            )
            .order_by(ProviderRawEvent.received_at.desc())
            .limit(1)
        )
        message_received_at = latest_message_at or record.last_message_received_at
        payload = {
            "source": "DLTV_FAST_SOCKET",
            "game_time_seconds": record.game_time_seconds,
            "radiant_kills": record.radiant_kills,
            "dire_kills": record.dire_kills,
            "radiant_nw_lead": record.radiant_nw_lead,
            "first_blood": record.first_blood,
            "canvas": record.canvas,
            "charts": record.charts,
            "source_game_time": record.source_game_time,
            "received_at": record.received_at,
            "last_message_received_at": message_received_at,
            "last_state_change_received_at": record.last_state_change_received_at,
            "connection_id": record.connection_id,
            "reconnect_generation": record.reconnect_generation,
        }
        complete = all(
            value is not None
            for value in (
                record.game_time_seconds,
                record.radiant_kills,
                record.dire_kills,
                record.radiant_nw_lead,
            )
        )
        return (
            payload,
            elapsed_seconds(decision_at, message_received_at),
            elapsed_seconds(decision_at, record.last_state_change_received_at),
            complete,
        )


def _market_pair_leg(record: OddsObservationRecord) -> MarketPairLeg:
    return MarketPairLeg(
        provider_match_id=record.provider_match_id,
        odds_id=record.odds_id,
        canonical_series_id=record.canonical_series_id,
        canonical_map_id=record.canonical_map_id,
        market_type=record.market_type,
        match_stage=record.match_stage,
        selection_team_id=record.selection_team_id,
        price=record.price,
        normalized_status=record.normalized_status,
        metadata_version=record.metadata_version,
        received_at=record.received_at,
    )


def _market_observation(record: OddsObservationRecord, fair_probability: float | None) -> dict:
    return {
        "odds_id": record.odds_id,
        "selection_team_id": (
            str(record.selection_team_id) if record.selection_team_id is not None else None
        ),
        "price": str(record.price),
        "implied_probability": record.implied_probability,
        "fair_probability": fair_probability,
        "raw_status": record.raw_status,
        "normalized_status": record.normalized_status,
        "metadata_version": record.metadata_version,
        "provider_updated_at": record.provider_updated_at,
        "received_at": record.received_at,
    }


def _roster_strength(players: list[dict[str, Any]]) -> float | None:
    combined: list[float] = []
    for player in players:
        values = [
            value for value in (player["base_strength"], player["recent_form"]) if value is not None
        ]
        if values:
            combined.append(mean(values))
    return mean(combined) if len(combined) == 5 else None


def _latest_cutoff(*values: datetime | None) -> datetime | None:
    available = [value for value in values if value is not None]
    return max(available) if available else None


def _sync_payload(record: LiveSyncEstimateRecord | None) -> dict[str, Any] | None:
    if record is None:
        return None
    return {
        "estimated_lag_seconds": record.estimated_lag_seconds,
        "p50_seconds": record.p50_seconds,
        "p90_seconds": record.p90_seconds,
        "jitter_seconds": record.jitter_seconds,
        "sample_size": record.sample_size,
        "accepted_pair_ratio": record.accepted_pair_ratio,
        "ambiguous_ratio": record.ambiguous_ratio,
        "outlier_ratio": record.outlier_ratio,
        "confidence": record.confidence,
        "status": record.status,
        "calculated_at": record.calculated_at,
    }


def _map_market_stages(map_number: int | None, *, best_of: int | None = None) -> tuple[str, ...]:
    if map_number is None:
        return ()
    stages = (
        f"r{map_number}",
        f"Map r{map_number}",
        f"map r{map_number}",
        f"Map {map_number}",
        f"map {map_number}",
    )
    if best_of is not None and map_number == best_of:
        # The deciding map's per-map winner market is withdrawn by RayBet
        # (r{n} goes stale, status 4) while the series winner ("final")
        # market stays live; for the deciding map that market IS the map
        # winner, so it joins the candidate stages and the freshest eligible
        # pair wins.
        stages += ("final",)
    return stages


class SnapshotBuilder(BaseSnapshotBuilder):
    """Production snapshot builder with side-aware identity and live anchors.

    Team A/B never map to Radiant/Dire by provider order: side evidence comes
    from explicit assignments, history is aligned to the series teams only when
    the side identity is RESOLVED, and delayed live data is dropped before any
    derived agreement is computed.
    """

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
            if live is not None:
                live["trend"] = await _live_trend(
                    session,
                    canonical_map_id=canonical_map_id,
                    decision_at=decision_at,
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
                live["enrichment"] = await _live_enrichment(
                    session,
                    valve_match_id=canonical_map.valve_match_id,
                    decision_at=decision_at,
                )
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
        live_anchors = {"real_start_anchor": None, "data_lag_seconds": None}
        if canonical_map_id is not None and canonical_map.valve_match_id is not None:
            live_anchors = await _live_anchors_payload(
                session,
                canonical_map_id=canonical_map_id,
                valve_match_id=canonical_map.valve_match_id,
                decision_at=decision_at,
            )
        if market is not None and canonical_map_id is not None:
            trajectory, drift = await _odds_path(
                session,
                canonical_map_id=canonical_map_id,
                expected_team_ids=(series.team_a_id, series.team_b_id),
                decision_at=decision_at,
            )
            market["odds_trajectory"] = trajectory
            if drift is not None:
                market["odds_drift"] = drift
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
            "live_anchors": live_anchors,
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


async def _live_trend(
    session: AsyncSession,
    *,
    canonical_map_id: UUID,
    decision_at: datetime,
) -> dict[str, Any]:
    rows = list(
        (
            await session.scalars(
                select(DltvLiveObservationRecord)
                .where(
                    DltvLiveObservationRecord.canonical_map_id == canonical_map_id,
                    DltvLiveObservationRecord.received_at <= decision_at,
                    DltvLiveObservationRecord.game_time_seconds.is_not(None),
                )
                .order_by(DltvLiveObservationRecord.received_at)
            )
        ).all()
    )
    if len(rows) < 2:
        return {"source": "DLTV_FAST_STATE_TRAJECTORY", "support_count": len(rows), "windows": {}}
    current = rows[-1]
    windows = {
        f"{seconds // 60}m": _live_window(rows, current=current, seconds=seconds)
        for seconds in (60, 180, 300, 600)
    }
    return {
        "source": "DLTV_FAST_STATE_TRAJECTORY",
        "support_count": len(rows),
        "current_game_time_seconds": current.game_time_seconds,
        "windows": windows,
        "momentum_side_5m": _side_from_delta(windows.get("5m", {}).get("nw_delta")),
        "last_lead_flip": _last_lead_flip(rows, current_game_time=current.game_time_seconds),
    }


def _live_window(rows: list[DltvLiveObservationRecord], *, current, seconds: int) -> dict[str, Any]:
    current_time = current.game_time_seconds
    if current_time is None:
        return _empty_live_window(seconds)
    target = current_time - seconds
    baseline = min(rows, key=lambda row: abs((row.game_time_seconds or 0) - target))
    if baseline.game_time_seconds is None or baseline is current:
        return _empty_live_window(seconds)
    tolerance = min(90, max(20, int(seconds * 0.25)))
    if abs(baseline.game_time_seconds - target) > tolerance:
        return _empty_live_window(seconds)
    effective = current_time - baseline.game_time_seconds
    if effective <= 0:
        return _empty_live_window(seconds)
    nw_delta = _int_delta(current.radiant_nw_lead, baseline.radiant_nw_lead)
    return {
        "requested_seconds": seconds,
        "available": nw_delta is not None,
        "baseline_game_time_seconds": baseline.game_time_seconds,
        "effective_seconds": effective,
        "nw_delta": nw_delta,
        "nw_velocity_per_minute": (nw_delta / (effective / 60.0) if nw_delta is not None else None),
        "radiant_kills_delta": _int_delta(current.radiant_kills, baseline.radiant_kills),
        "dire_kills_delta": _int_delta(current.dire_kills, baseline.dire_kills),
    }


def _last_lead_flip(
    rows: list[DltvLiveObservationRecord], *, current_game_time: int | None
) -> dict[str, Any] | None:
    previous = None
    latest = None
    for row in rows:
        if row.game_time_seconds is None or row.radiant_nw_lead in (None, 0):
            continue
        side = "RADIANT" if row.radiant_nw_lead > 0 else "DIRE"
        if previous is not None and side != previous:
            latest = {
                "from_side": previous,
                "to_side": side,
                "game_time_seconds": row.game_time_seconds,
                "seconds_ago_game_time": (
                    current_game_time - row.game_time_seconds
                    if current_game_time is not None
                    else None
                ),
            }
        previous = side
    return latest


def _empty_live_window(seconds: int) -> dict[str, Any]:
    return {
        "requested_seconds": seconds,
        "available": False,
        "baseline_game_time_seconds": None,
        "effective_seconds": None,
        "nw_delta": None,
        "nw_velocity_per_minute": None,
        "radiant_kills_delta": None,
        "dire_kills_delta": None,
    }


def _int_delta(current: int | None, baseline: int | None) -> int | None:
    return current - baseline if current is not None and baseline is not None else None


def _side_from_delta(value: object) -> str | None:
    if not isinstance(value, (int, float)):
        return None
    return "RADIANT" if value > 0 else "DIRE" if value < 0 else "EVEN"


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


async def _live_enrichment(
    session: AsyncSession,
    *,
    valve_match_id: int,
    decision_at: datetime,
) -> dict[str, Any]:
    """Load bootstrap-only enrichment (per-player stats, bans).

    The DLTV HTTP bootstrap payload (already archived Raw First) carries richer
    data than the fast socket.  It is parsed deterministically from the newest
    archived payload at or before decision_at; its own observed_at is carried so
    downstream consumers can discount stale enrichment.  This block does NOT gate
    LIVE_BASIC: the safety-critical freshness gate stays on the socket fields.
    """
    event = await session.scalar(
        select(ProviderRawEvent)
        .where(
            ProviderRawEvent.provider == "dltv",
            ProviderRawEvent.event_type == "DLTV_BOOTSTRAP",
            ProviderRawEvent.provider_key == str(valve_match_id),
            ProviderRawEvent.received_at <= decision_at,
        )
        .order_by(ProviderRawEvent.received_at.desc())
        .limit(1)
    )
    if event is None:
        return {"available": False, "observed_at": None}
    parsed = parse_live_enrichment(event.payload)
    parsed["available"] = True
    parsed["observed_at"] = event.received_at.isoformat()
    return parsed


async def _live_anchors_payload(
    session: AsyncSession,
    *,
    canonical_map_id: UUID,
    valve_match_id: int,
    decision_at: datetime,
) -> dict[str, Any]:
    """Real game-start anchor (picks ended) and broadcast clock-offset estimate.

    Production evidence shows DLTV delivery is real-time and the payload's
    is_picks_ended_time marks the real game start; the broadcast game clock may
    or may not include the ban/pick phase, so the clock alone cannot schedule
    real game-time decisions.  The offset between the derived broadcast clock
    start and the picks-ended time is positive only when the broadcast itself
    starts late (a true delay); negative offsets (BP-inclusive clocks) collapse
    to unknown.  All values are deterministic from archived data at or before
    decision_at.
    """
    picks_ended = await picks_ended_anchor(
        session, valve_match_id=valve_match_id, decision_at=decision_at
    )
    broadcast_start = await dltv_broadcast_start(
        session, canonical_map_id=canonical_map_id, decision_at=decision_at
    )
    lag = None
    if picks_ended is not None and broadcast_start is not None:
        lag = (broadcast_start - picks_ended).total_seconds()
        if lag < 0 or lag > 7_200:
            lag = None
    return {
        "real_start_anchor": picks_ended.isoformat() if picks_ended is not None else None,
        "data_lag_seconds": lag,
    }


async def _odds_path(
    session: AsyncSession,
    *,
    canonical_map_id: UUID,
    expected_team_ids: tuple[UUID, UUID],
    decision_at: datetime,
) -> tuple[list[dict[str, Any]] | None, dict[str, Any] | None]:
    """Odds change path and full-history drift for the market block.

    Returns (trajectory, drift):
    - trajectory is a token-compact display path: the first distinct change,
      the last change at or before decision_at - 5 minutes, and the most
      recent changes (at most 12 points, chronological);
    - drift is computed from the COMPLETE distinct-change history at or before
      decision_at and frozen into the snapshot, so compressing the display
      path can never change the statistics the model sees.
    """
    rows = list(
        (
            await session.scalars(
                select(OddsObservationRecord)
                .where(
                    OddsObservationRecord.canonical_map_id == canonical_map_id,
                    OddsObservationRecord.market_type == "Winner",
                    OddsObservationRecord.received_at <= decision_at,
                )
                .order_by(OddsObservationRecord.received_at)
            )
        ).all()
    )
    if not rows:
        return None, None
    team_order = {team_id: index for index, team_id in enumerate(expected_team_ids)}
    points: list[dict[str, Any]] = []
    last_pair: tuple[object, object] | None = None
    current_a: object = None
    current_b: object = None
    for record in rows:
        # Each observation row belongs to ONE selection; carry the other
        # side's latest price forward so every point is a complete A/B pair.
        side_index = team_order.get(record.selection_team_id)
        if side_index == 0:
            current_a = record.price
        elif side_index == 1:
            current_b = record.price
        else:
            continue
        pair = (current_a, current_b)
        if pair == last_pair and points:
            continue
        last_pair = pair
        points.append(
            {
                "received_at": record.received_at.isoformat(),
                "price_a": current_a,
                "price_b": current_b,
            }
        )
    if len(points) < 2:
        return None, None
    return _sample_odds_trajectory(points, decision_at), _odds_drift(points, decision_at)


def _sample_odds_trajectory(
    points: list[dict[str, Any]], decision_at: datetime
) -> list[dict[str, Any]]:
    """first change + 5m anchor + the most recent changes, chronological."""
    horizon = ensure_utc(decision_at) - timedelta(minutes=5)
    anchor: dict[str, Any] | None = None
    for point in points:
        received = _parse_iso_time(point.get("received_at"))
        if received is None:
            continue
        if ensure_utc(received) <= horizon:
            anchor = point
        else:
            break
    selected: list[dict[str, Any]] = [points[0]]
    seen = {points[0]["received_at"]}
    if anchor is not None and anchor["received_at"] not in seen:
        selected.append(anchor)
        seen.add(anchor["received_at"])
    for point in points[-9:]:
        if point["received_at"] not in seen:
            selected.append(point)
            seen.add(point["received_at"])
    # The anchor can sit inside the tail window; restore chronology.
    selected.sort(key=lambda point: point["received_at"])
    return selected


def _odds_drift(points: list[dict[str, Any]], decision_at: datetime) -> dict[str, Any] | None:
    """Drift metrics over the FULL distinct-change history (frozen at build)."""
    paired = [point for point in points if _float_value(point.get("price_a")) is not None]
    if len(paired) < 2:
        return None
    first = paired[0]
    last = paired[-1]
    first_a = _implied_probability(first.get("price_a"))
    last_a = _implied_probability(last.get("price_a"))
    if first_a is None or last_a is None:
        return None
    horizon = ensure_utc(decision_at) - timedelta(minutes=5)
    five_min_ago_a = None
    for point in paired:
        received = _parse_iso_time(point.get("received_at"))
        if received is None:
            continue
        if ensure_utc(received) <= horizon:
            five_min_ago_a = _implied_probability(point.get("price_a"))
    drift_pp = (last_a - first_a) * 100.0
    drift_5m_pp = (last_a - five_min_ago_a) * 100.0 if five_min_ago_a is not None else None
    price_first = float(first.get("price_a"))
    price_last = float(last.get("price_a"))
    if price_last < price_first - 1e-9:
        direction = "SHORTENED"
    elif price_last > price_first + 1e-9:
        direction = "LENGTHENED"
    else:
        direction = "FLAT"
    return {
        "price_a_first": price_first,
        "price_a_now": price_last,
        "implied_drift_pp_since_first": drift_pp,
        "implied_drift_pp_last_5m": drift_5m_pp,
        "direction": direction,
        "points": len(points),
    }


def _parse_iso_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _implied_probability(value: Any) -> float | None:
    number = _float_value(value)
    if number is None or number <= 0:
        return None
    return 1.0 / number


def _float_value(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    if isinstance(value, Decimal):
        return float(value)
    return None
