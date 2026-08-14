import re
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.events import DomainEvent, DomainEventType
from app.events.outbox import EventRepository
from app.market.odds_registry import OddsRegistry
from app.models import (
    CanonicalMap,
    OddsObservationRecord,
    ProviderMatchMapping,
    ProviderTeamMapping,
)
from app.providers.raybet.parser import (
    PARSER_VERSION,
    parse_odds_bootstrap,
    parse_socket_publish,
)
from app.repositories.raw import RawEventRepository
from app.time import ensure_utc


class RayBetOddsCollector:
    def __init__(
        self,
        *,
        raw_events: RawEventRepository,
        registry: OddsRegistry,
        events: EventRepository,
        significant_move: float,
    ) -> None:
        self._raw_events = raw_events
        self._registry = registry
        self._events = events
        self._significant_move = significant_move

    async def collect(
        self,
        session: AsyncSession,
        message: dict[str, Any],
        *,
        received_at: datetime | None = None,
    ) -> int:
        received = received_at or datetime.now(UTC)
        deltas = parse_socket_publish(message)
        provider_key = str(deltas[0].match_id) if deltas else None
        raw_event_id = await self._raw_events.append(
            session,
            provider="raybet",
            event_type="RAYBET_SOCKET_ODDS",
            provider_key=provider_key,
            payload=message,
            received_at=received,
            parser_version=PARSER_VERSION,
        )
        return await self._collect_deltas(
            session, deltas=deltas, raw_event_id=raw_event_id, received=received
        )

    async def collect_bootstrap(
        self,
        session: AsyncSession,
        payload: dict[str, Any],
        *,
        raw_event_id,
        received_at: datetime,
    ) -> int:
        return await self._collect_deltas(
            session,
            deltas=parse_odds_bootstrap(payload),
            raw_event_id=raw_event_id,
            received=received_at,
        )

    async def _collect_deltas(
        self,
        session: AsyncSession,
        *,
        deltas,
        raw_event_id,
        received: datetime,
    ) -> int:
        appended = 0
        for delta in deltas:
            metadata = await self._registry.get(session, delta.odds_id)
            if metadata is None:
                await self._events.record(
                    session,
                    DomainEvent(
                        event_type=DomainEventType.ODDS_REGISTRY_REFRESH_REQUIRED,
                        aggregate_type="raybet_match",
                        aggregate_id=str(delta.match_id),
                        dedupe_key=(
                            f"unknown-odds:{delta.match_id}:{received.strftime('%Y%m%d%H')}"
                        ),
                        payload={
                            "provider_match_id": delta.match_id,
                            "odds_id": delta.odds_id,
                        },
                        occurred_at=received,
                    ),
                )
                continue
            previous = await session.scalar(
                select(OddsObservationRecord)
                .where(OddsObservationRecord.odds_id == delta.odds_id)
                .order_by(OddsObservationRecord.received_at.desc())
                .limit(1)
            )
            if previous is not None and (
                previous.price == delta.price
                and previous.raw_status == delta.raw_status
                and _same_provider_time(previous.provider_updated_at, delta.provider_updated_at)
            ):
                continue
            match_mapping = await session.scalar(
                select(ProviderMatchMapping).where(
                    ProviderMatchMapping.provider == "raybet",
                    ProviderMatchMapping.provider_match_id == str(delta.match_id),
                )
            )
            canonical_map_id = match_mapping.canonical_map_id if match_mapping is not None else None
            canonical_series_id = (
                match_mapping.canonical_series_id if match_mapping is not None else None
            )
            if canonical_map_id is None and canonical_series_id is not None:
                map_number = _map_number(metadata.match_stage)
                if map_number is not None:
                    canonical_map_id = await session.scalar(
                        select(CanonicalMap.id).where(
                            CanonicalMap.series_id == canonical_series_id,
                            CanonicalMap.map_number == map_number,
                        )
                    )
            selection_team_id = None
            if metadata.team_id is not None:
                selection_team_id = await session.scalar(
                    select(ProviderTeamMapping.canonical_team_id).where(
                        ProviderTeamMapping.provider == "raybet",
                        ProviderTeamMapping.provider_team_id == str(metadata.team_id),
                    )
                )
            session.add(
                OddsObservationRecord(
                    provider_match_id=delta.match_id,
                    odds_id=delta.odds_id,
                    canonical_series_id=canonical_series_id,
                    canonical_map_id=canonical_map_id,
                    market_type=metadata.group_short_name,
                    match_stage=metadata.match_stage,
                    selection_team_id=selection_team_id,
                    price=delta.price,
                    implied_probability=1.0 / float(delta.price),
                    fair_probability=None,
                    overround=None,
                    raw_status=delta.raw_status,
                    normalized_status="UNKNOWN",
                    metadata_version=metadata.refreshed_at.isoformat(),
                    provider_updated_at=delta.provider_updated_at,
                    received_at=received,
                    raw_event_id=raw_event_id,
                )
            )
            appended += 1
            if previous is not None and canonical_series_id is not None:
                move = abs(float(delta.price) / float(previous.price) - 1.0)
                if move >= self._significant_move:
                    await self._events.record(
                        session,
                        DomainEvent(
                            event_type=DomainEventType.SIGNIFICANT_ODDS_MOVE,
                            aggregate_type="raybet_odds",
                            aggregate_id=str(delta.odds_id),
                            dedupe_key=(
                                f"odds-move:{delta.odds_id}:{delta.provider_updated_at or received}"
                            ),
                            payload={
                                "provider_match_id": delta.match_id,
                                "odds_id": delta.odds_id,
                                "relative_move": move,
                            },
                            occurred_at=received,
                        ),
                    )
        return appended


def _map_number(match_stage: str | None) -> int | None:
    if match_stage is None:
        return None
    match = re.fullmatch(
        r"(?i)\s*(?:r([1-9][0-9]*)|map\s*r?([1-9][0-9]*))\s*",
        match_stage,
    )
    if match is None:
        return None
    return int(match.group(1) or match.group(2))


def _same_provider_time(first: datetime | None, second: datetime | None) -> bool:
    if first is None or second is None:
        return first is second
    return ensure_utc(first) == ensure_utc(second)
