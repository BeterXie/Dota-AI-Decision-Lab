import asyncio
from datetime import UTC, datetime

import httpx

from app.providers.common import TimedPayload, create_system_ssl_context


class RayBetHttpClient:
    def __init__(self, base_url: str, origin: str, *, timeout_seconds: float = 8.0) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=timeout_seconds,
            verify=create_system_ssl_context(),
            headers={
                "Accept": "application/json, text/plain, */*",
                "Origin": origin,
                "Referer": f"{origin}/",
            },
        )

    async def get_games(self) -> TimedPayload:
        return await self._get("/game")

    async def get_matches(self, match_type: int, page: int = 1) -> TimedPayload:
        return await self._get("/match", params={"match_type": match_type, "page": page})

    async def get_odds(self, match_id: int) -> TimedPayload:
        return await self._get("/odds", params={"match_id": match_id})

    async def close(self) -> None:
        await self._client.aclose()

    async def _get(self, path: str, *, params: dict | None = None) -> TimedPayload:
        started = datetime.now(UTC)
        response = await self._client.get(path, params=params)
        if response.status_code == 204:
            await asyncio.sleep(0.25)
            response = await self._client.get(path, params=params)
        received = datetime.now(UTC)
        response.raise_for_status()
        if "application/json" not in response.headers.get("content-type", ""):
            raise ValueError("RayBet response is not JSON")
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("RayBet response must be a JSON object")
        return TimedPayload(
            payload=payload,
            request_started_at=started,
            received_at=received,
        )
