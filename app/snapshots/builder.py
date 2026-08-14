from dataclasses import dataclass
from datetime import datetime
from statistics import mean
from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.domain.snapshot import DecisionSnapshot, GateResult
from app.history.service import HistoricalIntelligenceService
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
    OddsObservationRecord,
    ProviderRawEvent,
)
from app.snapshots.gates import GateContext, evaluate_gate
from app.snapshots.repository import SnapshotRepository
from app.time import elapsed_seconds


@dataclass(frozen=True)
class SnapshotBuildOutcome:
    gate: GateResult
    snapshot: DecisionSnapshot | None


class SnapshotBuilder:
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
            criteria.append(OddsObservationRecord.match_stage.in_(_map_market_stages(map_number)))
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
        candidates = list(grouped.values())
        if not candidates:
            return None, None, False, (), ()
        evaluated = []
        for items in candidates:
            quality = evaluate_market_pair(
                tuple(_market_pair_leg(item) for item in items),
                expected_series_id=canonical_series_id,
                expected_map_id=canonical_map_id,
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


def _map_market_stages(map_number: int | None) -> tuple[str, ...]:
    if map_number is None:
        return ()
    return (
        f"r{map_number}",
        f"Map r{map_number}",
        f"map r{map_number}",
        f"Map {map_number}",
        f"map {map_number}",
    )
