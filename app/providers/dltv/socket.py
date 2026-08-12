import asyncio
from collections.abc import Awaitable, Callable
from uuid import uuid4

import socketio

EventHandler = Callable[[str, dict, str, int], Awaitable[None]]
StateHandler = Callable[[str, str | None], Awaitable[None]]


class DltvSocketClient:
    def __init__(self, base_url: str) -> None:
        self._base_url = base_url
        self._sio = socketio.AsyncClient(
            reconnection=True,
            reconnection_attempts=0,
            reconnection_delay=1,
            reconnection_delay_max=30,
        )
        self._stop = asyncio.Event()
        self._connection_id = ""
        self._reconnect_generation = 0

    async def run(self, on_event: EventHandler, on_state: StateHandler) -> None:
        @self._sio.event
        async def connect() -> None:
            self._reconnect_generation += 1
            self._connection_id = str(uuid4())
            await on_state("CONNECTED", None)

        @self._sio.event
        async def disconnect(reason: str | None = None) -> None:
            await on_state("DISCONNECTED", reason)

        @self._sio.on("*")
        async def catch_all(event: str, data: object) -> None:
            if event.startswith("__nd2_") and isinstance(data, dict):
                await on_event(
                    event,
                    data,
                    self._connection_id,
                    self._reconnect_generation,
                )

        await on_state("CONNECTING", None)
        try:
            await self._sio.connect(
                self._base_url,
                transports=["websocket", "polling"],
                socketio_path="socket.io",
                wait_timeout=10,
            )
            await self._sio.wait()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await on_state("FAILED", f"{type(exc).__name__}: {exc}")
            raise

    async def stop(self) -> None:
        self._stop.set()
        if self._sio.connected:
            await self._sio.disconnect()
