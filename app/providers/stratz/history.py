from datetime import datetime

from app.domain.history import HistoricalMatchBundle
from app.providers.common import TimedPayload
from app.providers.stratz.client import StratzClient
from app.providers.stratz.history_queries import (
    MATCH_QUERY,
    NORMALIZER_VERSION,
    TEAM_MATCHES_QUERY,
    normalize_match,
)


class StratzHistoricalProvider:
    name = "stratz"
    normalizer_version = NORMALIZER_VERSION

    def __init__(self, client: StratzClient) -> None:
        self._client = client

    async def get_team_pro_maps(
        self, team_id: str, *, before: datetime, limit: int
    ) -> TimedPayload:
        return await self._client.execute(
            operation_name="HistoricalTeamMatches",
            query=TEAM_MATCHES_QUERY,
            variables={"teamId": int(team_id), "take": limit},
        )

    async def get_player_pro_maps(
        self, account_id: int, *, before: datetime, limit: int
    ) -> TimedPayload:
        raise ValueError("STRATZ player history is synchronized from professional team maps")

    async def get_player_hero_maps(
        self,
        account_id: int,
        hero_id: int,
        *,
        before: datetime,
        limit: int,
    ) -> TimedPayload:
        raise ValueError("STRATZ player-hero history is synchronized from professional team maps")

    async def get_match_basic(self, match_id: int) -> TimedPayload:
        return await self._match(match_id)

    async def get_match_advanced(self, match_id: int) -> TimedPayload:
        return await self._match(match_id)

    def normalize_match(self, payload: dict, *, fetched_at: datetime) -> HistoricalMatchBundle:
        return normalize_match(payload, fetched_at=fetched_at)

    async def close(self) -> None:
        await self._client.close()

    async def _match(self, match_id: int) -> TimedPayload:
        return await self._client.execute(
            operation_name="HistoricalMatch",
            query=MATCH_QUERY,
            variables={"matchId": match_id},
        )
