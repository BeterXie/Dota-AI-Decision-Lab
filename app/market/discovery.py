from collections.abc import Awaitable, Callable
from typing import Protocol

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.domain.events import DomainEvent, DomainEventType
from app.events.outbox import EventRepository
from app.identity.raybet_linking import RayBetExistingSeriesLinker
from app.identity.resolver import IdentityAmbiguousError
from app.models import RayBetMatch
from app.providers.common import TimedPayload
from app.providers.liquipedia.runtime import LiquipediaRuntimeSeeder
from app.providers.raybet.parser import PARSER_VERSION, parse_matches
from app.repositories.raw import RawEventRepository

logger = structlog.get_logger()


class MatchHttpClient(Protocol):
    async def get_matches(self, match_type: int, page: int = 1) -> TimedPayload: ...


IdentityCallback = Callable[[AsyncSession, object], Awaitable[None]]


class RayBetDiscoveryService:
    def __init__(
        self,
        *,
        settings: Settings,
        client: MatchHttpClient,
        fallback_client: MatchHttpClient,
        raw_events: RawEventRepository,
        events: EventRepository,
        on_match: IdentityCallback,
        liquipedia_seeder: LiquipediaRuntimeSeeder | None = None,
        existing_series_linker: RayBetExistingSeriesLinker | None = None,
    ) -> None:
        self._settings = settings
        self._client = client
        self._fallback_client = fallback_client
        self._raw_events = raw_events
        self._events = events
        self._on_match = on_match
        self._liquipedia = liquipedia_seeder or LiquipediaRuntimeSeeder(raw_events)
        self._existing_series_linker = existing_series_linker or RayBetExistingSeriesLinker()

    async def discover_once(self, session: AsyncSession) -> int:
        await self._seed_liquipedia_without_blocking_raybet(session)
        discovered = 0
        for match_type in self._settings.raybet_discovery_match_types:
            for page in range(1, 11):
                response = await self._fetch(match_type, page)
                raw_event_id = await self._raw_events.append(
                    session,
                    provider="raybet",
                    event_type="RAYBET_MATCH_DISCOVERY",
                    provider_key=f"{match_type}:{page}",
                    payload=response.payload,
                    request_started_at=response.request_started_at,
                    received_at=response.received_at,
                    parser_version=PARSER_VERSION,
                )
                matches = parse_matches(
                    response.payload,
                    observed_at=response.received_at,
                    dota_game_id=self._settings.raybet_dota_game_id,
                    naive_timezone=self._settings.raybet_naive_timezone,
                )
                for match in matches:
                    session.add(
                        RayBetMatch(
                            provider_match_id=match.provider_match_id,
                            game_id=match.game_id,
                            tournament_id=match.tournament_id,
                            tournament_name=match.tournament_name,
                            team_a_provider_id=match.team_a_id,
                            team_a_name=match.team_a_name,
                            team_b_provider_id=match.team_b_id,
                            team_b_name=match.team_b_name,
                            round=match.round,
                            raw_status=match.provider_status,
                            scheduled_at=match.scheduled_at,
                            observed_at=match.observed_at,
                            raw_event_id=raw_event_id,
                        )
                    )
                    await session.flush()
                    try:
                        async with session.begin_nested():
                            link_result = await self._existing_series_linker.link(session, match)
                            if link_result.canonical_series_id is not None:
                                await self._on_match(session, match)
                            elif link_result.fallback_allowed:
                                await self._on_match(session, match)
                            else:
                                logger.warning(
                                    "raybet_identity_fallback_blocked",
                                    provider_match_id=match.provider_match_id,
                                    reason=link_result.reason,
                                )
                    except IdentityAmbiguousError as exc:
                        logger.warning(
                            "raybet_identity_ambiguous",
                            provider_match_id=match.provider_match_id,
                            code=str(exc),
                        )
                    await self._events.record(
                        session,
                        DomainEvent(
                            event_type=DomainEventType.MARKET_DISCOVERED,
                            aggregate_type="raybet_match",
                            aggregate_id=str(match.provider_match_id),
                            dedupe_key=f"raybet-match:{match.provider_match_id}",
                            payload={"provider_match_id": match.provider_match_id},
                            occurred_at=match.observed_at,
                        ),
                    )
                    discovered += 1
                result = response.payload.get("result")
                if not isinstance(result, list) or not result:
                    break
        return discovered

    async def close(self) -> None:
        await self._liquipedia.close()

    async def _seed_liquipedia_without_blocking_raybet(self, session: AsyncSession) -> None:
        try:
            async with session.begin_nested():
                result = await self._liquipedia.refresh_one_due(session)
        except Exception as exc:
            logger.warning(
                "liquipedia_seed_failed",
                error_type=type(exc).__name__,
                error=str(exc),
            )
            return
        if result.source is not None:
            logger.info(
                "liquipedia_seed_completed",
                source=result.source,
                observations=result.observations,
            )

    async def _fetch(self, match_type: int, page: int) -> TimedPayload:
        try:
            return await self._client.get_matches(match_type, page)
        except Exception as primary_error:
            try:
                return await self._fallback_client.get_matches(match_type, page)
            except Exception as fallback_error:
                raise RuntimeError(
                    "RayBet HTTP and curl transports both failed: "
                    f"{type(primary_error).__name__}; {type(fallback_error).__name__}"
                ) from fallback_error
