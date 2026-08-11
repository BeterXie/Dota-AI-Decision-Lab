from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.events import DomainEvent, DomainEventType
from app.events.outbox import EventRepository
from app.models import CanonicalMap, DltvLiveObservationRecord
from app.providers.dltv.parser import PARSER_VERSION, parse_fast_state, parse_series_frame
from app.repositories.raw import RawEventRepository
from app.snapshots.triggers import record_crossed_checkpoints


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

    async def collect(self, event_name: str, payload: dict[str, Any]) -> None:
        received_at = datetime.now(UTC)
        async with self._session_factory() as session, session.begin():
            raw_event_id = await self._raw_events.append(
                session,
                provider="dltv",
                event_type=(
                    "DLTV_FAST_SOCKET" if event_name.startswith("__nd2_match_") else "DLTV_SERIES"
                ),
                provider_key=event_name,
                payload=payload,
                received_at=received_at,
                parser_version=PARSER_VERSION,
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
                return
            if not event_name.startswith("__nd2_match_"):
                return
            try:
                valve_match_id = int(event_name.rsplit("_", 1)[1])
            except ValueError:
                return
            state = parse_fast_state(
                payload,
                valve_match_id=valve_match_id,
                received_at=received_at,
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
            latest = await session.scalar(
                select(DltvLiveObservationRecord)
                .where(DltvLiveObservationRecord.valve_match_id == valve_match_id)
                .order_by(DltvLiveObservationRecord.received_at.desc())
                .limit(1)
            )
            if latest is not None and latest.payload_hash == state.payload_hash:
                return
            session.add(
                DltvLiveObservationRecord(
                    canonical_map_id=canonical_map.id,
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
            await record_crossed_checkpoints(
                session,
                self._events,
                canonical_map_id=canonical_map.id,
                previous_game_time=(latest.game_time_seconds if latest is not None else None),
                current_game_time=state.game_time_seconds,
                checkpoint_minutes=self._checkpoint_minutes,
                observed_at=received_at,
            )
