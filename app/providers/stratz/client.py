import asyncio
from datetime import UTC, datetime
from typing import Any

import httpx

from app.providers.common import TimedPayload, create_system_ssl_context


class StratzClient:
    def __init__(
        self,
        endpoint: str,
        token: str,
        *,
        timeout_seconds: float = 20.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._token = token
        self._timeout_seconds = timeout_seconds
        self._owns_client = client is None
        self._client = client or self._new_client()
        self._last_request_at: datetime | None = None
        self._min_request_interval_seconds = 0.4
        self._request_lock = asyncio.Lock()

    async def execute(
        self,
        *,
        operation_name: str,
        query: str,
        variables: dict[str, Any],
    ) -> TimedPayload:
        async with self._request_lock:
            if self._last_request_at is not None:
                elapsed = (datetime.now(UTC) - self._last_request_at).total_seconds()
                if elapsed < self._min_request_interval_seconds:
                    await asyncio.sleep(self._min_request_interval_seconds - elapsed)
            started = datetime.now(UTC)
            request_payload = {
                "operationName": operation_name,
                "query": query,
                "variables": variables,
            }
            try:
                response = await self._client.post(self._endpoint, json=request_payload)
            except httpx.PoolTimeout:
                if not self._owns_client:
                    raise
                await self._reset_client()
                response = await self._client.post(self._endpoint, json=request_payload)
            self._last_request_at = datetime.now(UTC)
            received = self._last_request_at
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("STRATZ response must be a JSON object")
            return TimedPayload(
                payload=payload,
                request_started_at=started,
                received_at=received,
            )

    def _new_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=self._timeout_seconds,
            verify=create_system_ssl_context(),
            headers={
                "Authorization": f"Bearer {self._token}",
                "User-Agent": "Dota-AI-Decision-Lab",
            },
        )

    async def _reset_client(self) -> None:
        stale_client = self._client
        try:
            await stale_client.aclose()
        finally:
            self._client = self._new_client()

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()
