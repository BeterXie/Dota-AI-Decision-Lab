from datetime import datetime
from typing import Protocol

from app.domain.history import HistoricalMatchBundle
from app.providers.common import TimedPayload


class HistoricalProvider(Protocol):
    name: str
    normalizer_version: str

    async def get_team_pro_maps(
        self, team_id: str, *, before: datetime, limit: int
    ) -> TimedPayload: ...

    async def get_player_pro_maps(
        self, account_id: int, *, before: datetime, limit: int
    ) -> TimedPayload: ...

    async def get_player_hero_maps(
        self,
        account_id: int,
        hero_id: int,
        *,
        before: datetime,
        limit: int,
    ) -> TimedPayload: ...

    async def get_match_basic(self, match_id: int) -> TimedPayload: ...

    async def get_match_advanced(self, match_id: int) -> TimedPayload: ...

    def normalize_match(self, payload: dict, *, fetched_at: datetime) -> HistoricalMatchBundle: ...

    async def close(self) -> None: ...
