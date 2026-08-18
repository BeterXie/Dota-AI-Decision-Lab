from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.events import DomainEvent, DomainEventType
from app.domain.live import DltvFastState
from app.events.outbox import EventRepository
from app.live.anchor import picks_ended_anchor
from app.models import CanonicalMap, DltvLiveObservationRecord, ProviderRawEvent
from app.providers.dltv.parser import PARSER_VERSION, parse_fast_patch, parse_series_frame
from app.providers.dltv.reducer import reduce_fast_state
from app.repositories.raw import RawEventRepository
from app.snapshots.triggers import record_crossed_checkpoints

_ANCHOR_UNRESOLVED = object()


class DltvSocketCollector:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        raw_events: RawEventRepository,
        events: EventRepository,
        checkpoint_minutes: tuple[int, ...] = (),
    ) -> None:
        self._session_factory = session_factory
        self._raw_events = raw_events
        self._events = events
        self._checkpoint_minutes = checkpoint_minutes
        self._live_anchors: dict[UUID, datetime | None | object] = {}
        self._last_real_elapsed: dict[UUID, float] = {}

    async def collect(
        self,
        event_name: str,
        payload: dict[str, Any],
        connection_id: str | None = None,
        reconnect_generation: int = 0,
        *,
        received_at: datetime | None = None,
    ) -> None:
        received_at = received_at or datetime.now(UTC)
        is_match_event = event_name.startswith("__nd2_match_")
        async with self._session_factory() as session, session.begin():
            previous_socket_event = None
            previous_series_event = None
            if is_match_event:
                previous_socket_event = await session.scalar(
                    select(ProviderRawEvent)
                    .where(
                        ProviderRawEvent.provider == "dltv",
                        ProviderRawEvent.event_type == "DLTV_FAST_SOCKET",
                        ProviderRawEvent.provider_key == event_name,
                    )
                    .order_by(ProviderRawEvent.received_at.desc())
                    .limit(1)
                )
            elif event_name == "__nd2_series":
                previous_series_event = await session.scalar(
                    select(ProviderRawEvent)
                    .where(
                        ProviderRawEvent.provider == "dltv",
                        ProviderRawEvent.event_type == "DLTV_SERIES",
                        ProviderRawEvent.provider_key == event_name,
                    )
                    .order_by(ProviderRawEvent.received_at.desc())
                    .limit(1)
                )

            raw_event_id = await self._raw_events.append(
                session,
                provider="dltv",
                event_type="DLTV_FAST_SOCKET" if is_match_event else "DLTV_SERIES",
                provider_key=event_name,
                payload=payload,
                received_at=received_at,
                parser_version=PARSER_VERSION,
                connection_id=connection_id,
                reconnect_generation=reconnect_generation,
            )
            if event_name == "__nd2_series":
                frame = parse_series_frame(payload)
                for valve_match_id, series_id in frame.live_maps.items():
                    await self._events.record(
                        session,
                        DomainEvent(
                            event_type=DomainEventType.DLTV_MATCH_DISCOVERED,
                            aggregate_type="dltv_match",
                            aggregate_id=str(valve_match_id),
                            dedupe_key=f"dltv-live:{valve_match_id}",
                            payload={
                                "valve_match_id": valve_match_id,
                                "dltv_series_id": series_id,
                            },
                            occurred_at=received_at,
                        ),
                    )
                if (
                    previous_series_event is not None
                    and isinstance(previous_series_event.payload.get("live"), dict)
                    and isinstance(payload.get("live"), dict)
                ):
                    previous_frame = parse_series_frame(previous_series_event.payload)
                    for valve_match_id in previous_frame.live_maps.keys() - frame.live_maps.keys():
                        canonical_map = await session.scalar(
                            select(CanonicalMap).where(
                                CanonicalMap.valve_match_id == valve_match_id
                            )
                        )
                        if canonical_map is None:
                            continue
                        await self._events.record(
                            session,
                            DomainEvent(
                                event_type=DomainEventType.MAP_ENDED,
                                aggregate_type="canonical_map",
                                aggregate_id=str(canonical_map.id),
                                dedupe_key=f"map-ended:{canonical_map.id}",
                                payload={
                                    "canonical_map_id": str(canonical_map.id),
                                    "valve_match_id": valve_match_id,
                                },
                                occurred_at=received_at,
                            ),
                        )
                return
            if not is_match_event:
                return
            try:
                valve_match_id = int(event_name.rsplit("_", 1)[1])
            except ValueError:
                return
            patch = parse_fast_patch(
                payload,
                valve_match_id=valve_match_id,
                received_at=received_at,
                connection_id=connection_id,
                reconnect_generation=reconnect_generation,
            )
            canonical_map = await session.scalar(
                select(CanonicalMap).where(CanonicalMap.valve_match_id == valve_match_id)
            )
            if canonical_map is None:
                await self._events.record(
                    session,
                    DomainEvent(
                        event_type=DomainEventType.DLTV_MATCH_DISCOVERED,
                        aggregate_type="dltv_match",
                        aggregate_id=str(valve_match_id),
                        dedupe_key=f"dltv-socket:{valve_match_id}",
                        payload={"valve_match_id": valve_match_id},
                        occurred_at=received_at,
                    ),
                )
                return

            if _is_reconnect(previous_socket_event, connection_id, reconnect_generation):
                recovery_key = connection_id or f"generation-{reconnect_generation}"
                await self._events.record(
                    session,
                    DomainEvent(
                        event_type=DomainEventType.DLTV_MATCH_DISCOVERED,
                        aggregate_type="dltv_match",
                        aggregate_id=str(valve_match_id),
                        dedupe_key=f"dltv-reconnect:{valve_match_id}:{recovery_key}",
                        payload={
                            "valve_match_id": valve_match_id,
                            "connection_id": connection_id,
                            "previous_connection_id": (
                                previous_socket_event.connection_id
                                if previous_socket_event is not None
                                else None
                            ),
                            "reconnect_generation": reconnect_generation,
                            "previous_reconnect_generation": (
                                previous_socket_event.reconnect_generation
                                if previous_socket_event is not None
                                else None
                            ),
                            "reason": "SOCKET_RECONNECT_RECOVERY",
                        },
                        occurred_at=received_at,
                    ),
                )

            latest = await session.scalar(
                select(DltvLiveObservationRecord)
                .where(DltvLiveObservationRecord.valve_match_id == valve_match_id)
                .order_by(DltvLiveObservationRecord.received_at.desc())
                .limit(1)
            )
            previous = _state_from_record(latest) if latest is not None else None
            reduction = reduce_fast_state(previous, patch)
            raw_record = await session.scalar(
                select(ProviderRawEvent).where(ProviderRawEvent.id == raw_event_id)
            )
            if raw_record is not None:
                raw_record.normalized_state_hash = (
                    reduction.state.state_hash if reduction.state is not None else None
                )
                raw_record.is_duplicate = reduction.duplicate
            if reduction.state is None:
                return
            if not reduction.changed:
                # Duplicate socket packets still prove the DLTV stream is alive.
                # Refresh only the message-freshness metadata on the latest
                # normalized row; do NOT create a new observation or move
                # last_state_change_received_at, because the state did not change.
                if latest is not None:
                    latest.last_message_received_at = reduction.state.last_message_received_at
                    latest.connection_id = reduction.state.connection_id
                    latest.reconnect_generation = reduction.state.reconnect_generation
                return
            state = reduction.state
            session.add(
                DltvLiveObservationRecord(
                    canonical_map_id=canonical_map.id,
                    valve_match_id=valve_match_id,
                    game_time_seconds=state.game_time_seconds,
                    radiant_kills=state.radiant_kills,
                    dire_kills=state.dire_kills,
                    radiant_nw_lead=state.radiant_nw_lead,
                    first_blood=state.first_blood,
                    canvas=state.canvas,
                    charts=state.charts,
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
            if (
                state.game_time_seconds is not None
                and state.game_time_seconds > 0
                and (latest is None or not latest.game_time_seconds)
            ):
                await self._events.record(
                    session,
                    DomainEvent(
                        event_type=DomainEventType.MAP_STARTED,
                        aggregate_type="canonical_map",
                        aggregate_id=str(canonical_map.id),
                        dedupe_key=f"map-started:{canonical_map.id}",
                        payload={"canonical_map_id": str(canonical_map.id)},
                        occurred_at=received_at,
                    ),
                )
            real_elapsed_seconds: float | None = None
            previous_real_elapsed_seconds: float | None = None
            anchor = self._live_anchors.get(canonical_map.id, _ANCHOR_UNRESOLVED)
            if anchor is _ANCHOR_UNRESOLVED:
                resolved = await picks_ended_anchor(
                    session, valve_match_id=valve_match_id, decision_at=received_at
                )
                # Do NOT cache None: the bootstrap may not carry
                # is_picks_ended_time yet (picks still running); keep retrying
                # until it appears instead of pinning the fallback forever.
                if resolved is not None:
                    self._live_anchors[canonical_map.id] = resolved
                anchor = resolved
            if isinstance(anchor, datetime):
                real_elapsed_seconds = (received_at - anchor).total_seconds()
                previous_real_elapsed_seconds = self._last_real_elapsed.get(canonical_map.id)
                self._last_real_elapsed[canonical_map.id] = real_elapsed_seconds
            await record_crossed_checkpoints(
                session,
                self._events,
                canonical_map_id=canonical_map.id,
                previous_game_time=(latest.game_time_seconds if latest is not None else None),
                current_game_time=state.game_time_seconds,
                checkpoint_minutes=self._checkpoint_minutes,
                observed_at=received_at,
                real_elapsed_seconds=real_elapsed_seconds,
                previous_real_elapsed_seconds=previous_real_elapsed_seconds,
            )


def _is_reconnect(
    previous: ProviderRawEvent | None,
    connection_id: str | None,
    reconnect_generation: int,
) -> bool:
    if previous is None:
        return False
    if connection_id is not None:
        return previous.connection_id != connection_id
    previous_generation = previous.reconnect_generation
    return previous_generation is not None and reconnect_generation > previous_generation


def _state_from_record(record: DltvLiveObservationRecord) -> DltvFastState:
    return DltvFastState(
        valve_match_id=record.valve_match_id,
        game_time_seconds=record.game_time_seconds,
        radiant_kills=record.radiant_kills,
        dire_kills=record.dire_kills,
        radiant_nw_lead=record.radiant_nw_lead,
        first_blood=record.first_blood,
        canvas=record.canvas,
        charts=record.charts,
        source_game_time=record.source_game_time,
        last_message_received_at=record.last_message_received_at,
        last_state_change_received_at=record.last_state_change_received_at,
        state_hash=record.payload_hash,
        last_payload_hash=record.payload_hash,
        connection_id=record.connection_id,
        reconnect_generation=record.reconnect_generation,
    )
