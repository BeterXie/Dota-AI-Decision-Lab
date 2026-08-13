from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.canonical import content_digest
from app.domain.draft import DraftSlot, DraftValidation
from app.domain.events import DomainEvent, DomainEventType
from app.draft.role_assignment import DraftRoleAssignmentService
from app.events.outbox import EventRepository
from app.identity.resolver import IdentityResolver, ResolvedMap
from app.models import (
    CanonicalHero,
    CanonicalPlayer,
    DltvLiveObservationRecord,
    DraftSlotRecord,
    DraftSnapshotRecord,
)
from app.providers.dltv.bootstrap import DltvBootstrapClient
from app.providers.dltv.draft_picks import parse_dltv_provider_picks
from app.providers.dltv.parser import (
    PARSER_VERSION,
    parse_bootstrap_identity,
    parse_draft_labels,
    parse_fast_patch,
)
from app.providers.dltv.reducer import reduce_fast_state
from app.repositories.raw import RawEventRepository

VERIFIED_POSITION_SOURCES = {
    "STRATZ_CURRENT_MATCH",
    "HISTORICAL_ROLE_ASSIGNMENT",
    "MANUAL",
}


@dataclass(frozen=True)
class DltvBootstrapResult:
    resolved: ResolvedMap
    draft: DraftValidation
    draft_snapshot_id: UUID
    appended: bool


class DltvBootstrapCoordinator:
    def __init__(
        self,
        *,
        client: DltvBootstrapClient,
        raw_events: RawEventRepository,
        events: EventRepository,
        identities: IdentityResolver,
        role_assignment: DraftRoleAssignmentService | None = None,
    ) -> None:
        self._client = client
        self._raw_events = raw_events
        self._events = events
        self._identities = identities
        self._role_assignment = role_assignment or DraftRoleAssignmentService(
            stratz=None,
            raw_events=raw_events,
        )

    async def bootstrap(
        self,
        session: AsyncSession,
        *,
        valve_match_id: int,
        dltv_series_id: int | None = None,
    ) -> DltvBootstrapResult:
        response = await self._client.get_live(valve_match_id)
        raw_event_id = await self._raw_events.append(
            session,
            provider="dltv",
            event_type="DLTV_BOOTSTRAP",
            provider_key=str(valve_match_id),
            payload=response.payload,
            request_started_at=response.request_started_at,
            received_at=response.received_at,
            parser_version=PARSER_VERSION,
        )
        bootstrap_identity = parse_bootstrap_identity(
            response.payload, valve_match_id=valve_match_id
        )
        if bootstrap_identity.series_id is None and dltv_series_id is not None:
            bootstrap_identity = bootstrap_identity.model_copy(update={"series_id": dltv_series_id})
        resolved = await self._identities.resolve_dltv_bootstrap(session, bootstrap_identity)
        await self._events.record(
            session,
            DomainEvent(
                event_type=DomainEventType.DLTV_MATCH_RESOLVED,
                aggregate_type="canonical_map",
                aggregate_id=str(resolved.canonical_map_id),
                dedupe_key=f"dltv-resolved:{valve_match_id}",
                payload={
                    "canonical_map_id": str(resolved.canonical_map_id),
                    "valve_match_id": valve_match_id,
                },
                occurred_at=response.received_at,
            ),
        )

        provider_picks = parse_dltv_provider_picks(response.payload)
        resolution = await self._role_assignment.resolve(
            session,
            valve_match_id=valve_match_id,
            picks=provider_picks,
            observed_at=response.received_at,
        )
        draft = resolution.draft
        draft_observed_at = max(response.received_at, resolution.evidence_cutoff)
        player_names, hero_names = parse_draft_labels(response.payload)
        draft_hash = content_digest(
            {
                "complete": draft.complete,
                "slots": [slot.model_dump(mode="json") for slot in draft.slots],
                "blockers": draft.blockers,
                "warnings": draft.warnings,
            }
        )
        existing = await session.scalar(
            select(DraftSnapshotRecord)
            .where(
                DraftSnapshotRecord.canonical_map_id == resolved.canonical_map_id,
                DraftSnapshotRecord.payload_hash == draft_hash,
            )
            .order_by(DraftSnapshotRecord.observed_at.desc())
            .limit(1)
        )
        latest = await session.scalar(
            select(DraftSnapshotRecord)
            .where(DraftSnapshotRecord.canonical_map_id == resolved.canonical_map_id)
            .order_by(DraftSnapshotRecord.observed_at.desc())
            .limit(1)
        )
        if latest is not None and latest.complete and not draft.complete:
            latest_slots = await self._stored_slots(session, latest.id)
            if _positions_are_verified(latest_slots):
                await self._append_bootstrap_fast_state(
                    session,
                    canonical_map_id=resolved.canonical_map_id,
                    valve_match_id=valve_match_id,
                    payload=response.payload,
                    received_at=response.received_at,
                    raw_event_id=raw_event_id,
                )
                return DltvBootstrapResult(
                    resolved=resolved,
                    draft=DraftValidation(
                        complete=True,
                        slots=tuple(latest_slots),
                        blockers=(),
                        warnings=tuple(latest.warnings),
                    ),
                    draft_snapshot_id=latest.id,
                    appended=False,
                )
        if existing is not None:
            await self._append_bootstrap_fast_state(
                session,
                canonical_map_id=resolved.canonical_map_id,
                valve_match_id=valve_match_id,
                payload=response.payload,
                received_at=response.received_at,
                raw_event_id=raw_event_id,
            )
            return DltvBootstrapResult(
                resolved=resolved,
                draft=draft,
                draft_snapshot_id=existing.id,
                appended=False,
            )

        snapshot = DraftSnapshotRecord(
            canonical_map_id=resolved.canonical_map_id,
            valve_match_id=valve_match_id,
            complete=draft.complete,
            blockers=list(draft.blockers),
            warnings=list(draft.warnings),
            payload_hash=draft_hash,
            statistics_cutoff=draft_observed_at,
            observed_at=draft_observed_at,
            raw_event_id=raw_event_id,
        )
        session.add(snapshot)
        await session.flush()
        for slot in draft.slots:
            canonical_player_id: UUID | None = None
            if slot.account_id is not None:
                canonical_player_id = await self._identities.resolve_dltv_player(
                    session, slot.account_id
                )
                player = await session.get(CanonicalPlayer, canonical_player_id)
                player_name = player_names.get(slot.account_id)
                if player is not None and player_name is not None:
                    player.name = player_name
            if slot.hero_id is not None:
                await self._identities.resolve_dltv_hero(session, slot.hero_id)
                hero = await session.get(CanonicalHero, slot.hero_id)
                hero_name = hero_names.get(slot.hero_id)
                if hero is not None and hero_name is not None:
                    hero.name = hero_name
            session.add(
                DraftSlotRecord(
                    draft_snapshot_id=snapshot.id,
                    side=slot.side,
                    position=slot.position,
                    account_id=slot.account_id,
                    canonical_player_id=canonical_player_id,
                    hero_id=slot.hero_id,
                    source=slot.source,
                    confidence=slot.confidence,
                )
            )
        if draft.complete:
            await self._events.record(
                session,
                DomainEvent(
                    event_type=DomainEventType.DRAFT_CONFIRMED,
                    aggregate_type="canonical_map",
                    aggregate_id=str(resolved.canonical_map_id),
                    dedupe_key=f"draft:{resolved.canonical_map_id}:{draft_hash}",
                    payload={
                        "canonical_map_id": str(resolved.canonical_map_id),
                        "draft_snapshot_id": str(snapshot.id),
                    },
                    occurred_at=draft_observed_at,
                ),
            )
        await self._append_bootstrap_fast_state(
            session,
            canonical_map_id=resolved.canonical_map_id,
            valve_match_id=valve_match_id,
            payload=response.payload,
            received_at=response.received_at,
            raw_event_id=raw_event_id,
        )
        return DltvBootstrapResult(
            resolved=resolved,
            draft=draft,
            draft_snapshot_id=snapshot.id,
            appended=True,
        )

    async def _stored_slots(
        self, session: AsyncSession, draft_snapshot_id: UUID
    ) -> list[DraftSlot]:
        records = list(
            (
                await session.scalars(
                    select(DraftSlotRecord)
                    .where(DraftSlotRecord.draft_snapshot_id == draft_snapshot_id)
                    .order_by(DraftSlotRecord.side, DraftSlotRecord.position)
                )
            ).all()
        )
        return [
            DraftSlot(
                side=record.side,
                position=record.position,
                account_id=record.account_id,
                canonical_player_id=(
                    str(record.canonical_player_id)
                    if record.canonical_player_id is not None
                    else None
                ),
                hero_id=record.hero_id,
                source=record.source,
                confidence=record.confidence,
            )
            for record in records
        ]

    async def _append_bootstrap_fast_state(
        self,
        session: AsyncSession,
        *,
        canonical_map_id: UUID,
        valve_match_id: int,
        payload: dict,
        received_at: datetime,
        raw_event_id: UUID,
    ) -> None:
        reduction = reduce_fast_state(
            None,
            parse_fast_patch(
                payload,
                valve_match_id=valve_match_id,
                received_at=received_at,
            ),
        )
        if reduction.state is None:
            return
        state = reduction.state
        latest_hash = await session.scalar(
            select(DltvLiveObservationRecord.payload_hash)
            .where(DltvLiveObservationRecord.valve_match_id == valve_match_id)
            .order_by(DltvLiveObservationRecord.received_at.desc())
            .limit(1)
        )
        if latest_hash == state.state_hash:
            return
        session.add(
            DltvLiveObservationRecord(
                canonical_map_id=canonical_map_id,
                valve_match_id=valve_match_id,
                game_time_seconds=state.game_time_seconds,
                radiant_kills=state.radiant_kills,
                dire_kills=state.dire_kills,
                radiant_nw_lead=state.radiant_nw_lead,
                first_blood=state.first_blood,
                source_game_time=state.source_game_time,
                received_at=received_at,
                payload_hash=state.state_hash,
                connection_id=state.connection_id,
                reconnect_generation=state.reconnect_generation,
                last_message_received_at=state.last_message_received_at,
                last_state_change_received_at=state.last_state_change_received_at,
                raw_event_id=raw_event_id,
            )
        )


def _positions_are_verified(slots: list[DraftSlot]) -> bool:
    return len(slots) == 10 and all(slot.source in VERIFIED_POSITION_SOURCES for slot in slots)
