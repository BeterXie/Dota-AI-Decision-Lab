import asyncio
from datetime import UTC, datetime

from curl_cffi.requests import AsyncSession

from app.providers.common import TimedPayload


class CurlRayBetHttpClient:
    def __init__(self, base_url: str, origin: str, *, timeout_seconds: float = 8.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._origin = origin
        self._timeout = timeout_seconds
        self._session = AsyncSession()

    async def get_matches(self, match_type: int, page: int = 1) -> TimedPayload:
        return await self._get("/match", {"match_type": match_type, "page": page})

    async def get_odds(self, match_id: int) -> TimedPayload:
        return await self._get("/odds", {"match_id": match_id})

    async def close(self) -> None:
        await self._session.close()

    async def _get(self, path: str, params: dict) -> TimedPayload:
        started = datetime.now(UTC)
        response = await self._request(path, params)
        if response.status_code == 204:
            await asyncio.sleep(0.25)
            response = await self._request(path, params)
        received = datetime.now(UTC)
        response.raise_for_status()
        if "application/json" not in response.headers.get("content-type", ""):
            raise ValueError("RayBet curl response is not JSON")
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("RayBet curl response must be a JSON object")
        return TimedPayload(
            payload=payload,
            request_started_at=started,
            received_at=received,
        )

    async def _request(self, path: str, params: dict):
        return await asyncio.wait_for(
            self._session.get(
                f"{self._base_url}{path}",
                params=params,
                headers={"Accept": "application/json", "Origin": self._origin},
                impersonate="chrome",
            ),
            timeout=self._timeout,
        )
