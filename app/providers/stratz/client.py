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

    async def execute(
        self,
        *,
        operation_name: str,
        query: str,
        variables: dict[str, Any],
    ) -> TimedPayload:
        started = datetime.now(UTC)
        response = await self._client.post(
            self._endpoint,
            json={
                "operationName": operation_name,
                "query": query,
                "variables": variables,
            },
        )
        received = datetime.now(UTC)
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
