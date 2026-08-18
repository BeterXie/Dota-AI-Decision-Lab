from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.db import Base
from app.events.outbox import EventRepository
from app.identity.resolver import IdentityResolver
from app.market.discovery import RayBetDiscoveryService
from app.models import CanonicalSeries, ProviderMatchMapping, ProviderRawEvent
from app.providers.common import TimedPayload
from app.providers.liquipedia.fetch import FetchedPage
from app.providers.liquipedia.runtime import LiquipediaRuntimeSeeder
from app.repositories.raw import RawEventRepository

SCHEDULE_HTML = """
<table class="wikitable wikitable-striped infobox_matches_content">
  <tr>
    <td class="team-left"><a href="/dota2/Team_Liquid">Team Liquid</a></td>
    <td class="versus">vs. <span>(Bo3)</span></td>
    <td class="team-right"><a href="/dota2/Team_Spirit">Team Spirit</a></td>
  </tr>
  <tr>
    <td class="match-filler" colspan="3">
      <span data-timestamp="1787054400">12:00</span>
      <a href="/dota2/The_International/2026">The International 2026</a>
      - Group Stage
    </td>
  </tr>
</table>
"""

TOURNAMENT_HTML = """
<span class="tournaments-list-heading">Upcoming</span>
<ul class="tournaments-list-type-list"><li>
  <span class="tournaments-list-name">
    <a href="/dota2/The_International/2026">The International 2026</a>
  </span>
</li></ul>
"""


class FakeLiquipediaClient:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def parse_page(self, page_name: str) -> FetchedPage:
        self.calls.append(page_name)
        now = datetime(2026, 8, 18, 5, 0, tzinfo=UTC)
        html = SCHEDULE_HTML if page_name == "Liquipedia:Matches" else TOURNAMENT_HTML
        return FetchedPage(
            page_name=page_name,
            display_title=page_name,
            revision_id=len(self.calls),
            source_url=f"https://liquipedia.net/dota2/{page_name}",
            html=html,
            request_started_at=now,
            received_at=now,
            transport="httpx",
        )

    async def close(self) -> None:
        return None


class FailingSeeder:
    async def refresh_one_due(self, _session):
        raise RuntimeError("Liquipedia unavailable")

    async def close(self) -> None:
        return None


class EmptyRayBetClient:
    async def get_matches(self, _match_type: int, _page: int = 1) -> TimedPayload:
        now = datetime(2026, 8, 18, 5, 0, tzinfo=UTC)
        return TimedPayload(
            payload={"result": []},
            request_started_at=now,
            received_at=now,
        )


class MatchingRayBetClient:
    async def get_matches(self, _match_type: int, page: int = 1) -> TimedPayload:
        now = datetime(2026, 8, 18, 10, 0, tzinfo=UTC)
        result = []
        if page == 1:
            result = [
                {
                    "id": 38423263,
                    "game_id": 151,
                    "tournament_id": 9001,
                    "tournament_name": "TI 2026",
                    "round": "BO3",
                    "status": 1,
                    "start_time": "2026-08-18 20:12:00",
                    "team": [
                        {"pos": 1, "team_id": 16129, "team_name": "Liquid"},
                        {"pos": 2, "team_id": 16236, "team_name": "Spirit"},
                    ],
                }
            ]
        return TimedPayload(
            payload={"result": result},
            request_started_at=now,
            received_at=now,
        )


async def _noop_identity(_session, _match) -> None:
    return None


@pytest.mark.asyncio
async def test_runtime_seeder_refreshes_schedule_first_then_tournament_directory() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    client = FakeLiquipediaClient()
    seeder = LiquipediaRuntimeSeeder(
        RawEventRepository(),
        client=client,  # type: ignore[arg-type]
        schedule_refresh_seconds=3_600,
        tournament_refresh_seconds=21_600,
        minimum_parse_interval_seconds=0,
    )

    async with factory.begin() as session:
        first = await seeder.refresh_one_due(session)
    async with factory.begin() as session:
        second = await seeder.refresh_one_due(session)
    async with factory.begin() as session:
        third = await seeder.refresh_one_due(session)

    assert first.source == "schedule"
    assert first.observations == 1
    assert second.source == "tournaments"
    assert second.observations == 1
    assert third.source is None
    assert client.calls == ["Liquipedia:Matches", "Liquipedia:Tournaments"]
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(CanonicalSeries)) == 1
        raw_types = set(
            (
                await session.scalars(
                    select(ProviderRawEvent.event_type).where(
                        ProviderRawEvent.provider == "liquipedia"
                    )
                )
            ).all()
        )
        assert raw_types == {
            "LIQUIPEDIA_GLOBAL_SCHEDULE",
            "LIQUIPEDIA_TOURNAMENT_DIRECTORY",
        }
    await engine.dispose()


@pytest.mark.asyncio
async def test_liquipedia_seed_failure_does_not_block_raybet_discovery_transaction() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    client = EmptyRayBetClient()
    discovery = RayBetDiscoveryService(
        settings=Settings(_env_file=None, raybet_match_types="0"),
        client=client,
        fallback_client=client,
        raw_events=RawEventRepository(),
        events=EventRepository(),
        on_match=_noop_identity,
        liquipedia_seeder=FailingSeeder(),  # type: ignore[arg-type]
    )

    async with factory.begin() as session:
        discovered = await discovery.discover_once(session)

    assert discovered == 0
    async with factory() as session:
        raybet_raw = await session.scalar(
            select(func.count())
            .select_from(ProviderRawEvent)
            .where(ProviderRawEvent.provider == "raybet")
        )
        liquipedia_raw = await session.scalar(
            select(func.count())
            .select_from(ProviderRawEvent)
            .where(ProviderRawEvent.provider == "liquipedia")
        )
    assert raybet_raw == 1
    assert liquipedia_raw == 0
    await engine.dispose()


@pytest.mark.asyncio
async def test_same_discovery_pass_seeds_liquipedia_before_linking_raybet() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    raw_events = RawEventRepository()
    seeder = LiquipediaRuntimeSeeder(
        raw_events,
        client=FakeLiquipediaClient(),  # type: ignore[arg-type]
        minimum_parse_interval_seconds=0,
    )
    raybet = MatchingRayBetClient()
    identities = IdentityResolver()

    async def observe_match(session, match) -> None:
        await identities.observe_raybet_match(session, match)

    discovery = RayBetDiscoveryService(
        settings=Settings(_env_file=None, raybet_match_types="0"),
        client=raybet,
        fallback_client=raybet,
        raw_events=raw_events,
        events=EventRepository(),
        on_match=observe_match,
        liquipedia_seeder=seeder,
    )

    async with factory.begin() as session:
        discovered = await discovery.discover_once(session)

    assert discovered == 1
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(CanonicalSeries)) == 1
        mappings = list(
            (
                await session.scalars(
                    select(ProviderMatchMapping).where(
                        ProviderMatchMapping.provider.in_(("liquipedia", "raybet"))
                    )
                )
            ).all()
        )
        assert {mapping.provider for mapping in mappings} == {"liquipedia", "raybet"}
        assert len({mapping.canonical_series_id for mapping in mappings}) == 1
    await engine.dispose()
