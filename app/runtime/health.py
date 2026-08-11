import asyncio
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class WorkerState(StrEnum):
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    DEGRADED = "DEGRADED"
    RESTARTING = "RESTARTING"
    FAILED = "FAILED"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"


@dataclass
class WorkerHealth:
    name: str
    state: str = WorkerState.STARTING.value
    last_attempt_at: datetime | None = None
    last_success_at: datetime | None = None
    last_message_at: datetime | None = None
    consecutive_failures: int = 0
    last_error: str | None = None
    messages_received: int = 0
    restart_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class DependencyHealth:
    name: str
    status: str
    message: str | None = None
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = field(default_factory=dict)


class HealthRegistry:
    def __init__(self) -> None:
        self._workers: dict[str, WorkerHealth] = {}
        self._dependencies: dict[str, DependencyHealth] = {}
        self._lock = asyncio.Lock()

    async def worker_state(
        self,
        name: str,
        state: WorkerState,
        *,
        error: str | None = None,
        restart: bool = False,
    ) -> None:
        async with self._lock:
            health = self._workers.setdefault(name, WorkerHealth(name=name))
            health.state = state.value
            health.last_error = error
            if restart:
                health.restart_count += 1
            if state == WorkerState.RUNNING:
                health.consecutive_failures = 0

    async def attempt(self, name: str) -> None:
        async with self._lock:
            health = self._workers.setdefault(name, WorkerHealth(name=name))
            health.last_attempt_at = datetime.now(UTC)

    async def success(self, name: str, **metadata: Any) -> None:
        async with self._lock:
            health = self._workers.setdefault(name, WorkerHealth(name=name))
            health.last_success_at = datetime.now(UTC)
            health.consecutive_failures = 0
            health.last_error = None
            health.metadata.update(metadata)

    async def message(self, name: str, **metadata: Any) -> None:
        async with self._lock:
            health = self._workers.setdefault(name, WorkerHealth(name=name))
            health.last_message_at = datetime.now(UTC)
            health.messages_received += 1
            health.metadata.update(metadata)

    async def failure(self, name: str, error: str) -> None:
        async with self._lock:
            health = self._workers.setdefault(name, WorkerHealth(name=name))
            health.consecutive_failures += 1
            health.last_error = error

    async def dependency(
        self,
        name: str,
        status: str,
        *,
        message: str | None = None,
        **metadata: Any,
    ) -> None:
        async with self._lock:
            self._dependencies[name] = DependencyHealth(
                name=name,
                status=status,
                message=message,
                metadata=metadata,
            )

    async def worker(self, name: str) -> dict[str, Any]:
        async with self._lock:
            return asdict(self._workers.setdefault(name, WorkerHealth(name=name)))

    async def snapshot(self) -> dict[str, Any]:
        async with self._lock:
            workers = {name: asdict(value) for name, value in self._workers.items()}
            dependencies = {name: asdict(value) for name, value in self._dependencies.items()}
        return {
            "overall": _overall_status(dependencies),
            "workers": workers,
            "dependencies": dependencies,
            "observed_at": datetime.now(UTC),
        }


def _overall_status(dependencies: dict[str, dict[str, Any]]) -> str:
    database = dependencies.get("DATABASE", {}).get("status")
    if database not in {"READY"}:
        return "ACTION_REQUIRED"
    ai_statuses = [dependencies.get(name, {}).get("status") for name in ("GPT", "CLAUDE", "GEMINI")]
    if ai_statuses and all(status == "ACTION_REQUIRED" for status in ai_statuses):
        return "ACTION_REQUIRED"
    degraded = {
        "DEGRADED",
        "ACTION_REQUIRED",
        "UNKNOWN",
        "UNSAFE",
        "CAUTION",
        "FAILED",
    }
    if any(item.get("status") in degraded for item in dependencies.values()):
        return "DEGRADED"
    return "READY"
