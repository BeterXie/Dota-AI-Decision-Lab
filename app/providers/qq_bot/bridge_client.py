"""HTTP client for the local QQ Bot Node bridge."""

import httpx

from app.providers.common import create_system_ssl_context
from app.providers.qq_bot.models import (
    QQBridgeEventBatch,
    QQBridgeHealth,
    QQInboundMessage,
)


class QQBridgeError(RuntimeError):
    pass


class QQBridgeClient:
    def __init__(
        self,
        *,
        base_url: str,
        timeout_seconds: float = 15.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=self._base_url,
            timeout=httpx.Timeout(timeout_seconds),
            verify=create_system_ssl_context(),
            headers={"User-Agent": "Dota-AI-Decision-Lab/0.1.0"},
        )

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def health(self) -> QQBridgeHealth:
        raw = await self._request("GET", "/health")
        return QQBridgeHealth.model_validate(raw)

    async def events(self, cursor: int = 0) -> QQBridgeEventBatch:
        raw = await self._request("GET", "/events", params={"cursor": cursor})
        try:
            events = tuple(
                QQInboundMessage.model_validate(item)
                for item in raw.get("events") or []
                if isinstance(item, dict)
            )
        except Exception as exc:
            raise QQBridgeError(f"invalid event payload from QQ bridge: {exc}") from exc
        cursor_value = raw.get("cursor")
        return QQBridgeEventBatch(
            events=events,
            cursor=cursor_value if isinstance(cursor_value, int) and cursor_value >= 0 else 0,
        )

    async def send_text(
        self,
        *,
        scope: str,
        target_id: str,
        text: str,
        msg_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> str:
        if scope not in {"c2c", "group"}:
            raise ValueError("QQ scope must be c2c or group")
        body: dict[str, object] = {
            "scope": scope,
            "target_id": target_id,
            "text": text,
        }
        if msg_id:
            body["msg_id"] = msg_id
        if idempotency_key:
            body["idempotency_key"] = idempotency_key
        raw = await self._request("POST", "/send", body=body)
        message_id = raw.get("message_id")
        if not isinstance(message_id, str) or not message_id:
            raise QQBridgeError("QQ bridge send response is missing message_id")
        return message_id

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, object] | None = None,
        body: dict[str, object] | None = None,
    ) -> dict:
        try:
            response = await self._client.request(
                method,
                f"{self._base_url}{path}",
                params=params,
                json=body,
                timeout=self._timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise QQBridgeError(f"QQ bridge request failed: {type(exc).__name__}: {exc}") from exc
        if response.is_error:
            detail = response.text.strip()[:300]
            raise QQBridgeError(
                f"QQ bridge returned HTTP {response.status_code}: {detail or '(no body)'}"
            )
        try:
            raw = response.json()
        except ValueError as exc:
            raise QQBridgeError("QQ bridge returned non-JSON response") from exc
        if not isinstance(raw, dict):
            raise QQBridgeError("QQ bridge response must be a JSON object")
        return raw
