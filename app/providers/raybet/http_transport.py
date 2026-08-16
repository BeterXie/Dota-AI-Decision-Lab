import asyncio
from datetime import UTC, datetime
from random import uniform

from curl_cffi.requests import AsyncSession

from app.providers.common import TimedPayload


class CurlRayBetHttpClient:
    def __init__(
        self,
        base_url: str,
        origin: str,
        *,
        timeout_seconds: float = 8.0,
        max_attempts: int = 2,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        self._max_attempts = max_attempts
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
        response = None
        for attempt in range(self._max_attempts):
            try:
                response = await self._request(path, params)
            except OSError, TimeoutError:
                if attempt + 1 >= self._max_attempts:
                    raise
                await asyncio.sleep(0.25 * (attempt + 1) + uniform(0.0, 0.15))  # noqa: S311 - retry jitter is not security-sensitive randomness
                continue
            if response.status_code not in (403, 429, 500, 502, 503, 504, 204):
                break
            if attempt + 1 < self._max_attempts:
                await asyncio.sleep(0.25 * (attempt + 1) + uniform(0.0, 0.15))  # noqa: S311 - retry jitter is not security-sensitive randomness
        if response is None:
            raise RuntimeError("RayBet curl request produced no response")
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


class CurlRayBetHttpPool:
    def __init__(self, clients: tuple[CurlRayBetHttpClient, ...]) -> None:
        if not clients:
            raise ValueError("RayBet curl pool requires at least one client")
        self._clients = clients
        self._preferred_index = 0

    async def get_matches(self, match_type: int, page: int = 1) -> TimedPayload:
        return await self._request("get_matches", match_type, page)

    async def get_odds(self, match_id: int) -> TimedPayload:
        return await self._request("get_odds", match_id)

    async def close(self) -> None:
        for client in self._clients:
            await client.close()

    async def _request(self, method: str, *args) -> TimedPayload:
        failures: list[str] = []
        for offset in range(len(self._clients)):
            index = (self._preferred_index + offset) % len(self._clients)
            client = self._clients[index]
            try:
                response = await getattr(client, method)(*args)
            except Exception as exc:
                failures.append(f"{type(exc).__name__}: {exc}")
                continue
            self._preferred_index = index
            return response
        raise RuntimeError("RayBet curl hosts failed: " + "; ".join(failures))
