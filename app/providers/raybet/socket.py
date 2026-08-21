import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Protocol

from curl_cffi import requests

MessageHandler = Callable[[dict], Awaitable[None]]
StateHandler = Callable[[str, str | None], Awaitable[None]]


class RayBetSocketConnection(Protocol):
    async def send(self, value: str) -> None: ...

    async def recv(self) -> str | bytes | tuple[bytes, int]: ...


class RayBetSocketClient:
    def __init__(
        self,
        url: str,
        origin: str,
        *,
        business_message_timeout_seconds: float = 120.0,
    ) -> None:
        if business_message_timeout_seconds <= 0:
            raise ValueError("business_message_timeout_seconds must be positive")
        self._url = url
        self._origin = origin
        self._business_message_timeout = business_message_timeout_seconds
        self._stop = asyncio.Event()
        self._curl_session: requests.AsyncSession | None = None

    async def run(self, on_publish: MessageHandler, on_state: StateHandler) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            try:
                await on_state("CONNECTING", None)
                async with self._connect() as websocket:
                    buffered = await self._handshake(websocket)
                    await on_state("CONNECTED", None)
                    backoff = 1.0
                    message_deadline = (
                        asyncio.get_running_loop().time() + self._business_message_timeout
                    )
                    for message in buffered:
                        if self._stop.is_set():
                            break
                        await on_publish(message)
                        message_deadline = (
                            asyncio.get_running_loop().time() + self._business_message_timeout
                        )
                    while not self._stop.is_set():
                        remaining = message_deadline - asyncio.get_running_loop().time()
                        if remaining <= 0:
                            raise TimeoutError(self._business_timeout_message())
                        try:
                            raw = await asyncio.wait_for(websocket.recv(), timeout=remaining)
                        except TimeoutError as exc:
                            raise TimeoutError(self._business_timeout_message()) from exc
                        if isinstance(raw, tuple):
                            raw = raw[0]
                        if isinstance(raw, bytes):
                            raw = raw.decode("utf-8")
                        if self._stop.is_set():
                            break
                        if raw == "#1":
                            await _send_text(websocket, "#2")
                            continue
                        message = _match_publish(raw)
                        if message is not None:
                            await on_publish(message)
                            message_deadline = (
                                asyncio.get_running_loop().time() + self._business_message_timeout
                            )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                await on_state("DISCONNECTED", f"{type(exc).__name__}: {exc}")
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=backoff)
                except TimeoutError:
                    pass
                backoff = min(backoff * 2, 30.0)

    def _business_timeout_message(self) -> str:
        return (
            "RayBet match channel produced no business message for "
            f"{self._business_message_timeout:g} seconds"
        )

    async def stop(self) -> None:
        self._stop.set()
        if self._curl_session is not None:
            await self._curl_session.close()
            self._curl_session = None

    def _connect(self):
        if self._curl_session is None:
            self._curl_session = requests.AsyncSession()
        return self._curl_session.ws_connect(
            self._url,
            headers={"Origin": self._origin, "Referer": f"{self._origin}/"},
            impersonate="chrome",
            timeout=10,
        )

    async def _handshake(self, websocket: RayBetSocketConnection) -> list[dict]:
        await _send_text(
            websocket,
            json.dumps(
                {"event": "#handshake", "data": {"authToken": None}, "cid": 1},
                separators=(",", ":"),
            ),
        )
        buffered = await self._wait_for_rid(websocket, 1)
        await _send_text(
            websocket,
            json.dumps(
                {"event": "#subscribe", "data": {"channel": "match"}, "cid": 2},
                separators=(",", ":"),
            ),
        )
        buffered.extend(await self._wait_for_rid(websocket, 2))
        return buffered

    async def _wait_for_rid(self, websocket: RayBetSocketConnection, rid: int) -> list[dict]:
        buffered: list[dict] = []
        while True:
            raw = await asyncio.wait_for(websocket.recv(), timeout=10)
            if isinstance(raw, tuple):
                raw = raw[0]
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            if raw == "#1":
                await _send_text(websocket, "#2")
                continue
            if not isinstance(raw, str):
                continue
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if message.get("rid") == rid:
                return buffered
            if _is_match_publish(message):
                buffered.append(message)


async def _send_text(websocket: RayBetSocketConnection, value: str) -> None:
    send_str = getattr(websocket, "send_str", None)
    if send_str is not None:
        await send_str(value)
        return
    await websocket.send(value)


def _match_publish(raw: object) -> dict | None:
    if not isinstance(raw, str):
        return None
    try:
        message = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return message if _is_match_publish(message) else None


def _is_match_publish(message: object) -> bool:
    return (
        isinstance(message, dict)
        and message.get("event") == "#publish"
        and isinstance(message.get("data"), dict)
        and message["data"].get("channel") == "match"
    )
