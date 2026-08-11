import asyncio
from collections.abc import Awaitable, Callable
from typing import Protocol

from app.runtime.health import HealthRegistry


class RuntimeWorker(Protocol):
    name: str

    async def start(self) -> None: ...

    async def run(self) -> None: ...

    async def stop(self) -> None: ...

    async def health(self) -> dict: ...


class PeriodicWorker:
    def __init__(
        self,
        *,
        name: str,
        interval_seconds: float,
        action: Callable[[], Awaitable[None]],
        health_registry: HealthRegistry,
        run_immediately: bool = True,
    ) -> None:
        self.name = name
        self._interval = interval_seconds
        self._action = action
        self._health = health_registry
        self._run_immediately = run_immediately
        self._stop = asyncio.Event()

    async def start(self) -> None:
        return None

    async def run(self) -> None:
        if not self._run_immediately:
            await self._wait()
        while not self._stop.is_set():
            await self._health.attempt(self.name)
            try:
                await self._action()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                await self._health.failure(self.name, f"{type(exc).__name__}: {exc}")
                raise
            await self._health.success(self.name)
            await self._wait()

    async def stop(self) -> None:
        self._stop.set()

    async def health(self) -> dict:
        return await self._health.worker(self.name)

    async def _wait(self) -> None:
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=self._interval)
        except TimeoutError:
            return


class ServiceWorker:
    def __init__(
        self,
        *,
        name: str,
        run: Callable[[], Awaitable[None]],
        stop: Callable[[], Awaitable[None]],
        health_registry: HealthRegistry,
    ) -> None:
        self.name = name
        self._run = run
        self._stop = stop
        self._health = health_registry

    async def start(self) -> None:
        return None

    async def run(self) -> None:
        await self._run()

    async def stop(self) -> None:
        await self._stop()

    async def health(self) -> dict:
        return await self._health.worker(self.name)
