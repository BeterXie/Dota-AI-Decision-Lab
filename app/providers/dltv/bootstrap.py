from datetime import UTC, datetime

import httpx

from app.providers.common import TimedPayload, create_system_ssl_context


class DltvBootstrapClient:
    def __init__(self, base_url: str, *, timeout_seconds: float = 8.0) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=timeout_seconds,
            verify=create_system_ssl_context(),
        )

    async def get_live(self, valve_match_id: int) -> TimedPayload:
        started = datetime.now(UTC)
        response = await self._client.get(f"/live/{valve_match_id}.json")
        received = datetime.now(UTC)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("DLTV live response must be a JSON object")
        return TimedPayload(
            payload=payload,
            request_started_at=started,
            received_at=received,
        )

    async def close(self) -> None:
        await self._client.aclose()
