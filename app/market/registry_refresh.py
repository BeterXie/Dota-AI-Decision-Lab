from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.market.collector import RayBetOddsCollector
from app.market.odds_registry import OddsRegistry
from app.providers.common import TimedPayload
from app.providers.raybet.parser import PARSER_VERSION, parse_odds_registry
from app.repositories.raw import RawEventRepository


class OddsHttpClient(Protocol):
    async def get_odds(self, match_id: int) -> TimedPayload: ...


class RayBetRegistryRefreshService:
    def __init__(
        self,
        client: OddsHttpClient,
        fallback_client: OddsHttpClient,
        raw_events: RawEventRepository,
        registry: OddsRegistry,
        collector: RayBetOddsCollector,
    ) -> None:
        self._client = client
        self._fallback_client = fallback_client
        self._raw_events = raw_events
        self._registry = registry
        self._collector = collector

    async def refresh(self, session: AsyncSession, provider_match_id: int) -> int:
        try:
            response = await self._client.get_odds(provider_match_id)
        except Exception as primary_error:
            try:
                response = await self._fallback_client.get_odds(provider_match_id)
            except Exception as fallback_error:
                raise RuntimeError(
                    "RayBet odds bootstrap transports failed: "
                    f"{type(primary_error).__name__}; {type(fallback_error).__name__}"
                ) from fallback_error
        raw_event_id = await self._raw_events.append(
            session,
            provider="raybet",
            event_type="RAYBET_ODDS_BOOTSTRAP",
            provider_key=str(provider_match_id),
            payload=response.payload,
            request_started_at=response.request_started_at,
            received_at=response.received_at,
            parser_version=PARSER_VERSION,
        )
        metadata = parse_odds_registry(response.payload)
        await self._registry.replace_match_metadata(
            session,
            metadata=metadata,
            raw_event_id=raw_event_id,
            refreshed_at=response.received_at,
        )
        await self._collector.collect_bootstrap(
            session,
            response.payload,
            raw_event_id=raw_event_id,
            received_at=response.received_at,
        )
        return len(metadata)
