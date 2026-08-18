from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import Base
from app.models import ProviderRawEvent
from app.providers.liquipedia.discovery import LiquipediaDiscoveryService
from app.providers.liquipedia.fetch import FetchedPage
from app.repositories.raw import RawEventRepository


class FakeMediaWikiClient:
    async def parse_page(self, page_name: str) -> FetchedPage:
        now = datetime(2026, 8, 18, 5, 0, tzinfo=UTC)
        return FetchedPage(
            page_name=page_name,
            display_title="Tournament directory",
            revision_id=4242,
            source_url="https://liquipedia.net/dota2/Liquipedia:Tournaments",
            html="""
            <span class="tournaments-list-heading">Upcoming</span>
            <ul class="tournaments-list-type-list"><li>
              <span class="tournaments-list-name">
                <a href="/dota2/The_International/2026">The International 2026</a>
              </span>
            </li></ul>
            """,
            request_started_at=now,
            received_at=now,
            transport="httpx",
        )


@pytest.mark.asyncio
async def test_discovery_persists_revision_source_transport_and_raw_html() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    service = LiquipediaDiscoveryService(FakeMediaWikiClient(), RawEventRepository())  # type: ignore[arg-type]

    async with factory.begin() as session:
        observations = await service.discover_tournaments(session)

    assert len(observations) == 1
    async with factory() as session:
        raw = await session.scalar(
            select(ProviderRawEvent).where(ProviderRawEvent.provider == "liquipedia")
        )
        assert raw is not None
        assert raw.provider_key == "Liquipedia:Tournaments"
        assert raw.payload["revision_id"] == 4242
        assert raw.payload["transport"] == "httpx"
        assert raw.payload["observation_count"] == 1
        assert "The_International/2026" in raw.payload["html"]
        assert raw.parser_version == "liquipedia-mediawiki-v1"
    await engine.dispose()
