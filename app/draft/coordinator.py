from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.canonical import content_digest
from app.domain.events import DomainEvent, DomainEventType
from app.events.outbox import EventRepository
from app.identity.resolver import IdentityResolver, ResolvedMap
from app.models import (
    DltvLiveObservationRecord,
    DraftSlotRecord,
    DraftSnapshotRecord,
)
from app.providers.dltv.bootstrap import DltvBootstrapClient
from app.providers.dltv.parser import (
    PARSER_VERSION,
    parse_bootstrap_identity,
    parse_draft,
    parse_fast_state,
)
from app.repositories.raw import RawEventRepository


class DltvBootstrapCoordinator:
    def __init__(
        self,
        *,
        client: DltvBootstrapClient,
        raw_events: RawEventRepository,
        events: EventRepository,
        identities: IdentityResolver,
    ) -> None:
        self._client = client
        self._raw_events = raw_events
        self._events = events
        self._identities = identities

    async def bootstrap(
        self,
        session: AsyncSession,
        *,
        valve_match_id: int,
        dltv_series_id: int | None = None,
    ) -> ResolvedMap:
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
        draft = parse_draft(response.payload)
        draft_hash = content_digest([slot.model_dump(mode="json") for slot in draft.slots])
        snapshot = DraftSnapshotRecord(
            canonical_map_id=resolved.canonical_map_id,
            valve_match_id=valve_match_id,
            complete=draft.complete,
            blockers=list(draft.blockers),
            warnings=list(draft.warnings),
            payload_hash=draft_hash,
            statistics_cutoff=response.received_at,
            observed_at=response.received_at,
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
            await self._identities.resolve_dltv_hero(session, slot.hero_id)
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
                    occurred_at=response.received_at,
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
        return resolved

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
        state = parse_fast_state(payload, valve_match_id=valve_match_id, received_at=received_at)
        latest_hash = await session.scalar(
            select(DltvLiveObservationRecord.payload_hash)
            .where(DltvLiveObservationRecord.valve_match_id == valve_match_id)
            .order_by(DltvLiveObservationRecord.received_at.desc())
            .limit(1)
        )
        if latest_hash == state.payload_hash:
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
                payload_hash=state.payload_hash,
                raw_event_id=raw_event_id,
            )
        )
