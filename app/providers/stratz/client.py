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
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=timeout_seconds,
            verify=create_system_ssl_context(),
            headers={"Authorization": f"Bearer {token}", "User-Agent": "Dota-AI-Decision-Lab"},
        )
        self._last_request_at: datetime | None = None
        self._min_request_interval_seconds = 0.4

    async def execute(
        self,
        *,
        operation_name: str,
        query: str,
        variables: dict[str, Any],
    ) -> TimedPayload:
        if self._last_request_at is not None:
            elapsed = (datetime.now(UTC) - self._last_request_at).total_seconds()
            if elapsed < self._min_request_interval_seconds:
                await asyncio.sleep(self._min_request_interval_seconds - elapsed)
        started = datetime.now(UTC)
        response = await self._client.post(
            self._endpoint,
            json={
                "operationName": operation_name,
                "query": query,
                "variables": variables,
            },
        )
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

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()
