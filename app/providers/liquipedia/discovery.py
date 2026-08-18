from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.providers.liquipedia.fetch import FetchedPage, LiquipediaMediaWikiClient
from app.providers.liquipedia.models import (
    LiquipediaSeriesObservation,
    LiquipediaTournamentObservation,
)
from app.providers.liquipedia.parser import parse_series, parse_tournaments, parser_version
from app.repositories.raw import RawEventRepository


class LiquipediaDiscoveryService:
    def __init__(
        self,
        client: LiquipediaMediaWikiClient,
        raw_events: RawEventRepository,
    ) -> None:
        self._client = client
        self._raw_events = raw_events

    async def discover_tournaments(
        self,
        session: AsyncSession,
    ) -> list[LiquipediaTournamentObservation]:
        page = await self._client.parse_page("Liquipedia:Tournaments")
        observations = parse_tournaments(page.html)
        await self._store_page(
            session,
            page,
            event_type="LIQUIPEDIA_TOURNAMENT_DIRECTORY",
            observation_count=len(observations),
        )
        return observations

    async def discover_global_schedule(
        self,
        session: AsyncSession,
    ) -> list[LiquipediaSeriesObservation]:
        page = await self._client.parse_page("Liquipedia:Matches")
        observations = parse_series(page.html)
        await self._store_page(
            session,
            page,
            event_type="LIQUIPEDIA_GLOBAL_SCHEDULE",
            observation_count=len(observations),
        )
        return observations

    async def discover_tournament_schedule(
        self,
        session: AsyncSession,
        page_name: str,
    ) -> list[LiquipediaSeriesObservation]:
        page = await self._client.parse_page(page_name)
        observations = parse_series(page.html)
        await self._store_page(
            session,
            page,
            event_type="LIQUIPEDIA_TOURNAMENT_SCHEDULE",
            observation_count=len(observations),
        )
        return observations

    async def _store_page(
        self,
        session: AsyncSession,
        page: FetchedPage,
        *,
        event_type: str,
        observation_count: int,
    ) -> None:
        await self._raw_events.append(
            session,
            provider="liquipedia",
            event_type=event_type,
            provider_key=page.page_name,
            payload={
                "page_name": page.page_name,
                "display_title": page.display_title,
                "revision_id": page.revision_id,
                "source_url": page.source_url,
                "transport": page.transport,
                "html": page.html,
                "observation_count": observation_count,
            },
            request_started_at=page.request_started_at,
            received_at=page.received_at,
            parser_version=parser_version(),
        )
