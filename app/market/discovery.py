from collections.abc import Awaitable, Callable
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.domain.events import DomainEvent, DomainEventType
from app.events.outbox import EventRepository
from app.models import RayBetMatch
from app.providers.common import TimedPayload
from app.providers.raybet.parser import PARSER_VERSION, parse_matches
from app.repositories.raw import RawEventRepository


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
    ) -> None:
        self._settings = settings
        self._client = client
        self._fallback_client = fallback_client
        self._raw_events = raw_events
        self._events = events
        self._on_match = on_match

    async def discover_once(self, session: AsyncSession) -> int:
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
                    await self._on_match(session, match)
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
