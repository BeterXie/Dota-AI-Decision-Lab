from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.db import Base
from app.events.outbox import EventRepository
from app.identity.raybet_linking import RayBetLinkResult
from app.identity.resolver import IdentityAmbiguousError
from app.market.discovery import RayBetDiscoveryService
from app.models import DomainEventRecord, RayBetMatch
from app.providers.common import TimedPayload
from app.providers.liquipedia.runtime import LiquipediaSeedResult
from app.repositories.raw import RawEventRepository


class NoopSeeder:
    async def refresh_one_due(self, _session) -> LiquipediaSeedResult:
        return LiquipediaSeedResult(source=None)

    async def close(self) -> None:
        return None


class TwoMatchClient:
    async def get_matches(self, _match_type: int, page: int = 1) -> TimedPayload:
        now = datetime(2026, 8, 18, 10, 0, tzinfo=UTC)
        result = []
        if page == 1:
            result = [
                {
                    "id": 1001,
                    "game_id": 151,
                    "tournament_id": 77,
                    "tournament_name": "Event A",
                    "round": "BO3",
                    "status": 1,
                    "start_time": "2026-08-18 20:00:00",
                    "team": [
                        {"pos": 1, "team_id": 1, "team_name": "Team A"},
                        {"pos": 2, "team_id": 2, "team_name": "Team B"},
                    ],
                },
                {
                    "id": 1002,
                    "game_id": 151,
                    "tournament_id": 78,
                    "tournament_name": "Event B",
                    "round": "BO3",
                    "status": 1,
                    "start_time": "2026-08-18 21:00:00",
                    "team": [
                        {"pos": 1, "team_id": 3, "team_name": "Team C"},
                        {"pos": 2, "team_id": 4, "team_name": "Team D"},
                    ],
                },
            ]
        return TimedPayload(
            payload={"result": result},
            request_started_at=now,
            received_at=now,
        )


class FirstMatchAmbiguousLinker:
    async def link(self, _session, match) -> RayBetLinkResult:
        if match.provider_match_id == 1001:
            raise IdentityAmbiguousError("RAYBET_EXISTING_SERIES_AMBIGUOUS")
        return RayBetLinkResult(None, "no_liquipedia_candidate")


@pytest.mark.asyncio
async def test_one_ambiguous_match_does_not_rollback_or_stop_discovery_pass() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    client = TwoMatchClient()
    observed: list[int] = []

    async def on_match(_session, match) -> None:
        observed.append(match.provider_match_id)

    discovery = RayBetDiscoveryService(
        settings=Settings(_env_file=None, raybet_match_types="0"),
        client=client,
        fallback_client=client,
        raw_events=RawEventRepository(),
        events=EventRepository(),
        on_match=on_match,
        liquipedia_seeder=NoopSeeder(),  # type: ignore[arg-type]
        existing_series_linker=FirstMatchAmbiguousLinker(),  # type: ignore[arg-type]
    )

    async with factory.begin() as session:
        discovered = await discovery.discover_once(session)

    assert discovered == 2
    assert observed == []
    async with factory() as session:
        match_count = await session.scalar(select(func.count()).select_from(RayBetMatch))
        event_count = await session.scalar(select(func.count()).select_from(DomainEventRecord))
        event_ids = set(
            (
                await session.scalars(
                    select(DomainEventRecord.aggregate_id).where(
                        DomainEventRecord.event_type == "MARKET_DISCOVERED"
                    )
                )
            ).all()
        )
    assert match_count == 2
    assert event_count == 2
    assert event_ids == {"1001", "1002"}
    await engine.dispose()
