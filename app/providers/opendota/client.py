import asyncio
from datetime import UTC, datetime
from typing import Any

import httpx

from app.domain.history import HistoricalMatchBundle
from app.providers.common import TimedPayload, create_system_ssl_context
from app.providers.opendota.normalizer import NORMALIZER_VERSION, normalize_match


class OpenDotaClient:
    name = "opendota"
    normalizer_version = NORMALIZER_VERSION

    def __init__(
        self,
        base_url: str,
        api_key: str | None = None,
        *,
        timeout_seconds: float = 20.0,
    ) -> None:
        headers = {"User-Agent": "Dota-AI-Decision-Lab"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout_seconds,
            verify=create_system_ssl_context(),
            headers=headers,
        )
        self._last_request_at: datetime | None = None
        self._min_request_interval_seconds = 60.0 / 30.0
        self._request_lock = asyncio.Lock()

    async def get_team_catalog(self, page: int = 0) -> TimedPayload:
        return await self._get("/teams", params={"page": page})

    async def get_team_players(self, team_id: str | int) -> TimedPayload:
        return await self._get(f"/teams/{team_id}/players")

    async def get_team_pro_maps(
        self, team_id: str, *, before: datetime, limit: int
    ) -> TimedPayload:
        response = await self._get(f"/teams/{team_id}/matches")
        matches = response.payload if isinstance(response.payload, list) else []
        filtered = [
            item
            for item in matches
            if isinstance(item, dict)
            and isinstance(item.get("start_time"), int)
            and datetime.fromtimestamp(item["start_time"], tz=UTC) < before
        ][:limit]
        return response.model_copy(update={"payload": {"matches": filtered}})

    async def get_player_pro_maps(
        self, account_id: int, *, before: datetime, limit: int
    ) -> TimedPayload:
        return await self._player_matches(account_id, before=before, limit=limit)

    async def get_player_hero_maps(
        self,
        account_id: int,
        hero_id: int,
        *,
        before: datetime,
        limit: int,
    ) -> TimedPayload:
        return await self._player_matches(account_id, before=before, limit=limit, hero_id=hero_id)

    async def get_match_basic(self, match_id: int) -> TimedPayload:
        return await self._get(f"/matches/{match_id}")

    async def get_match_advanced(self, match_id: int) -> TimedPayload:
        return await self.get_match_basic(match_id)

    def normalize_match(self, payload: dict, *, fetched_at: datetime) -> HistoricalMatchBundle:
        return normalize_match(payload, fetched_at=fetched_at)

    async def close(self) -> None:
        await self._client.aclose()

    async def _player_matches(
        self,
        account_id: int,
        *,
        before: datetime,
        limit: int,
        hero_id: int | None = None,
    ) -> TimedPayload:
        params: dict[str, Any] = {
            "limit": limit,
            "significant": 1,
            "project": (
                "match_id,start_time,leagueid,hero_id,player_slot,is_radiant,win,"
                "kills,deaths,assists,gold_per_min,xp_per_min,last_hits,hero_damage,"
                "tower_damage,total_gold,position_est,patch"
            ),
        }
        if hero_id is not None:
            params["hero_id"] = hero_id
        response = await self._get(f"/players/{account_id}/matches", params=params)
        matches = response.payload if isinstance(response.payload, list) else []
        filtered = [
            item
            for item in matches
            if isinstance(item, dict)
            and item.get("leagueid")
            and isinstance(item.get("start_time"), int)
            and datetime.fromtimestamp(item["start_time"], tz=UTC) < before
        ][:limit]
        return response.model_copy(update={"payload": {"matches": filtered}})

    async def _get(self, path: str, *, params: dict[str, Any] | None = None) -> TimedPayload:
        async with self._request_lock:
            if self._last_request_at is not None:
                elapsed = (datetime.now(UTC) - self._last_request_at).total_seconds()
                if elapsed < self._min_request_interval_seconds:
                    await asyncio.sleep(self._min_request_interval_seconds - elapsed)
            result = await self._request(path, params=params)
            self._last_request_at = datetime.now(UTC)
            return result

    async def _request(self, path: str, *, params: dict[str, Any] | None = None) -> TimedPayload:
        started = datetime.now(UTC)
        response = await self._client.get(path, params=params)
        received = datetime.now(UTC)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, (dict, list)):
            raise ValueError("OpenDota response must be a JSON object or array")
        return TimedPayload(
            payload=payload,
            request_started_at=started,
            received_at=received,
        )
