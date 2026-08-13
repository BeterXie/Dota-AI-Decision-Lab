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
    def __init__(self, url: str, origin: str) -> None:
        self._url = url
        self._origin = origin
        self._stop = asyncio.Event()
        self._curl_session: requests.AsyncSession | None = None

    async def run(self, on_publish: MessageHandler, on_state: StateHandler) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            try:
                await on_state("CONNECTING", None)
                async with self._connect() as websocket:
                    await self._handshake(websocket)
                    await on_state("CONNECTED", None)
                    backoff = 1.0
                    while not self._stop.is_set():
                        raw = await websocket.recv()
                        if isinstance(raw, tuple):
                            raw = raw[0]
                        if isinstance(raw, bytes):
                            raw = raw.decode("utf-8")
                        if self._stop.is_set():
                            break
                        if raw == "#1":
                            await _send_text(websocket, "#2")
                            continue
                        if not isinstance(raw, str):
                            continue
                        try:
                            message = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        if (
                            message.get("event") == "#publish"
                            and message.get("data", {}).get("channel") == "match"
                        ):
                            await on_publish(message)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                await on_state("DISCONNECTED", f"{type(exc).__name__}: {exc}")
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=backoff)
                except TimeoutError:
                    pass
                backoff = min(backoff * 2, 30.0)

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

    async def _handshake(self, websocket: RayBetSocketConnection) -> None:
        await _send_text(
            websocket,
            json.dumps(
                {"event": "#handshake", "data": {"authToken": None}, "cid": 1},
                separators=(",", ":"),
            ),
        )
        await self._wait_for_rid(websocket, 1)
        await _send_text(
            websocket,
            json.dumps(
                {"event": "#subscribe", "data": {"channel": "match"}, "cid": 2},
                separators=(",", ":"),
            ),
        )
        await self._wait_for_rid(websocket, 2)

    async def _wait_for_rid(self, websocket: RayBetSocketConnection, rid: int) -> None:
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
                return


async def _send_text(websocket: RayBetSocketConnection, value: str) -> None:
    send_str = getattr(websocket, "send_str", None)
    if send_str is not None:
        await send_str(value)
        return
    await websocket.send(value)
