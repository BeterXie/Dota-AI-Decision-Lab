from datetime import UTC, datetime
from typing import Any

import httpx

from app.providers.common import TimedPayload


class StratzClient:
    def __init__(self, endpoint: str, token: str, *, timeout_seconds: float = 20.0) -> None:
        self._client = httpx.AsyncClient(
            base_url=endpoint,
            timeout=timeout_seconds,
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
            "",
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
        await self._client.aclose()
