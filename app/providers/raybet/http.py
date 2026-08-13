import asyncio
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from random import uniform

import httpx

from app.providers.common import TimedPayload, create_system_ssl_context


class RayBetHttpClient:
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
        response = None
        for attempt in range(self._max_attempts):
            try:
                response = await self._client.get(path, params=params)
            except httpx.HTTPError:
                if attempt + 1 >= self._max_attempts:
                    raise
                await asyncio.sleep(0.25 * (attempt + 1))
                continue
            if response.status_code not in (403, 429, 500, 502, 503, 504, 204):
                break
            if attempt + 1 < self._max_attempts:
                delay = _retry_after_seconds(response.headers.get("retry-after"))
                await asyncio.sleep(delay + uniform(0.0, 0.15))
        if response is None:
            raise RuntimeError("RayBet request produced no response")
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


def _retry_after_seconds(value: str | None) -> float:
    if not value:
        return 0.25
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            return max(0.0, (parsedate_to_datetime(value) - datetime.now(UTC)).total_seconds())
        except TypeError, ValueError, OverflowError:
            return 0.25


class RayBetHttpPool:
    """Rotate across the same host list used by the RayBet web client."""

    def __init__(self, clients: tuple[RayBetHttpClient, ...]) -> None:
        if not clients:
            raise ValueError("RayBet HTTP pool requires at least one client")
        self._clients = clients
        self._preferred_index = 0

    async def get_games(self) -> TimedPayload:
        return await self._request("get_games")

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
        raise RuntimeError("RayBet HTTP hosts failed: " + "; ".join(failures))
