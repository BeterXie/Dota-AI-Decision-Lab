import asyncio
import random

import structlog

from app.runtime.health import HealthRegistry, WorkerState
from app.runtime.worker import RuntimeWorker

logger = structlog.get_logger()


class Supervisor:
    def __init__(
        self,
        workers: list[RuntimeWorker],
        *,
        health: HealthRegistry,
        max_backoff_seconds: float,
    ) -> None:
        self._workers = workers
        self._health = health
        self._max_backoff = max_backoff_seconds
        self._stop = asyncio.Event()
        self._tasks: list[asyncio.Task] = []

    async def run(self) -> None:
        for worker in self._workers:
            await self._health.worker_state(worker.name, WorkerState.STARTING)
            await worker.start()
            self._tasks.append(
                asyncio.create_task(self._supervise(worker), name=f"worker:{worker.name}")
            )
        await self._stop.wait()

    async def stop(self) -> None:
        if self._stop.is_set():
            return
        self._stop.set()
        for worker in self._workers:
            await self._health.worker_state(worker.name, WorkerState.STOPPING)
        await asyncio.gather(*(worker.stop() for worker in self._workers), return_exceptions=True)
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        for worker in self._workers:
            await self._health.worker_state(worker.name, WorkerState.STOPPED)

    async def _supervise(self, worker: RuntimeWorker) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            await self._health.worker_state(worker.name, WorkerState.RUNNING)
            try:
                await worker.run()
                if self._stop.is_set():
                    return
                raise RuntimeError("worker exited unexpectedly")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                await self._health.failure(worker.name, error)
                await self._health.worker_state(
                    worker.name,
                    WorkerState.RESTARTING,
                    error=error,
                    restart=True,
                )
                logger.error(
                    "worker_crashed",
                    worker=worker.name,
                    error_type=type(exc).__name__,
                    error=str(exc),
                )
                delay = min(backoff, self._max_backoff) * random.uniform(0.8, 1.2)
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=delay)
                    return
                except TimeoutError:
                    backoff = min(backoff * 2.0, self._max_backoff)
