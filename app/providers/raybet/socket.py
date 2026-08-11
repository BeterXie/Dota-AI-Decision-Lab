import asyncio
import json
from collections.abc import Awaitable, Callable

from websockets.asyncio.client import ClientConnection, connect

MessageHandler = Callable[[dict], Awaitable[None]]
StateHandler = Callable[[str, str | None], Awaitable[None]]


class RayBetSocketClient:
    def __init__(self, url: str, origin: str) -> None:
        self._url = url
        self._origin = origin
        self._stop = asyncio.Event()

    async def run(self, on_publish: MessageHandler, on_state: StateHandler) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            try:
                await on_state("CONNECTING", None)
                async with connect(
                    self._url,
                    origin=self._origin,
                    ping_interval=None,
                    open_timeout=10,
                ) as websocket:
                    await self._handshake(websocket)
                    await on_state("CONNECTED", None)
                    backoff = 1.0
                    async for raw in websocket:
                        if self._stop.is_set():
                            break
                        if raw == "#1":
                            await websocket.send("#2")
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

    async def _handshake(self, websocket: ClientConnection) -> None:
        await websocket.send(
            json.dumps(
                {"event": "#handshake", "data": {"authToken": None}, "cid": 1},
                separators=(",", ":"),
            )
        )
        await self._wait_for_rid(websocket, 1)
        await websocket.send(
            json.dumps(
                {"event": "#subscribe", "data": {"channel": "match"}, "cid": 2},
                separators=(",", ":"),
            )
        )
        await self._wait_for_rid(websocket, 2)

    async def _wait_for_rid(self, websocket: ClientConnection, rid: int) -> None:
        while True:
            raw = await asyncio.wait_for(websocket.recv(), timeout=10)
            if raw == "#1":
                await websocket.send("#2")
                continue
            if not isinstance(raw, str):
                continue
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if message.get("rid") == rid:
                return
