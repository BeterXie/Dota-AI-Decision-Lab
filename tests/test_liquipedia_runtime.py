from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.config
import app.db
import app.events.outbox
import app.market.discovery
import app.models
import app.providers.common
import app.providers.liquipedia.fetch
import app.providers.liquipedia.runtime
import app.repositories.raw


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

    async def parse_page(self, page_name: str) -> app.providers.liquipedia.fetch.FetchedPage:
        self.calls.append(page_name)
        now = datetime(2026, 8, 18, 5, 0, tzinfo=UTC)
        html = SCHEDULE_HTML if page_name == "Liquipedia:Matches" else TOURNAMENT_HTML
        return app.providers.liquipedia.fetch.FetchedPage(
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
    async def get_matches(
        self, _match_type: int, _page: int = 1
    ) -> app.providers.common.TimedPayload:
        now = datetime(2026, 8, 18, 5, 0, tzinfo=UTC)
        return app.providers.common.TimedPayload(
            payload={"result": []},
            request_started_at=now,
            received_at=now,
        )


async def _noop_identity(_session, _match) -> None:
    return None


@pytest.mark.asyncio
async def test_runtime_seeder_refreshes_schedule_first_then_tournament_directory() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(app.db.Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    client = FakeLiquipediaClient()
    seeder = app.providers.liquipedia.runtime.LiquipediaRuntimeSeeder(
        app.repositories.raw.RawEventRepository(),
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
        assert (
            await session.scalar(select(func.count()).select_from(app.models.CanonicalSeries)) == 1
        )
        raw_types = set(
            (
                await session.scalars(
                    select(app.models.ProviderRawEvent.event_type).where(
                        app.models.ProviderRawEvent.provider == "liquipedia"
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
        await connection.run_sync(app.db.Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    client = EmptyRayBetClient()
    discovery = app.market.discovery.RayBetDiscoveryService(
        settings=app.config.Settings(_env_file=None, raybet_match_types="0"),
        client=client,
        fallback_client=client,
        raw_events=app.repositories.raw.RawEventRepository(),
        events=app.events.outbox.EventRepository(),
        on_match=_noop_identity,
        liquipedia_seeder=FailingSeeder(),  # type: ignore[arg-type]
    )

    async with factory.begin() as session:
        discovered = await discovery.discover_once(session)

    assert discovered == 0
    async with factory() as session:
        raybet_raw = await session.scalar(
            select(func.count())
            .select_from(app.models.ProviderRawEvent)
            .where(app.models.ProviderRawEvent.provider == "raybet")
        )
        liquipedia_raw = await session.scalar(
            select(func.count())
            .select_from(app.models.ProviderRawEvent)
            .where(app.models.ProviderRawEvent.provider == "liquipedia")
        )
    assert raybet_raw == 1
    assert liquipedia_raw == 0
    await engine.dispose()
