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
    last_attempt_at: datetime | None = None
    last_success_at: datetime | None = None
    last_message_at: datetime | None = None
    consecutive_failures: int = 0
    last_error: str | None = None
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    requires_message: bool = False
    max_message_age_seconds: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class HealthRegistry:
    def __init__(self) -> None:
        self._workers: dict[str, WorkerHealth] = {}
        self._dependencies: dict[str, DependencyHealth] = {}

    async def worker_state(
        self,
        name: str,
        state: WorkerState,
        *,
        error: str | None = None,
        restart: bool = False,
    ) -> None:
        health = self._workers.setdefault(name, WorkerHealth(name=name))
        health.state = state.value
        health.last_error = error
        if restart:
            health.restart_count += 1
        if state == WorkerState.RUNNING:
            health.consecutive_failures = 0

    async def attempt(self, name: str) -> None:
        health = self._workers.setdefault(name, WorkerHealth(name=name))
        health.last_attempt_at = datetime.now(UTC)

    async def success(self, name: str, **metadata: Any) -> None:
        health = self._workers.setdefault(name, WorkerHealth(name=name))
        health.last_success_at = datetime.now(UTC)
        health.consecutive_failures = 0
        health.last_error = None
        health.metadata.update(metadata)

    async def message(self, name: str, **metadata: Any) -> None:
        health = self._workers.setdefault(name, WorkerHealth(name=name))
        health.last_message_at = datetime.now(UTC)
        health.messages_received += 1
        health.metadata.update(metadata)

    async def failure(self, name: str, error: str) -> None:
        health = self._workers.setdefault(name, WorkerHealth(name=name))
        health.consecutive_failures += 1
        health.last_error = error

    async def dependency(
        self,
        name: str,
        status: str,
        *,
        message: str | None = None,
        business_message: bool = False,
        requires_message: bool | None = None,
        max_message_age_seconds: float | None = None,
        **metadata: Any,
    ) -> None:
        now = datetime.now(UTC)
        health = self._dependencies.setdefault(
            name,
            DependencyHealth(name=name, status=status),
        )
        health.status = status
        health.message = message
        health.last_attempt_at = now
        health.updated_at = now
        if requires_message is not None:
            health.requires_message = requires_message
        if max_message_age_seconds is not None:
            health.max_message_age_seconds = max_message_age_seconds
        if business_message:
            health.last_message_at = now
        if status in {"READY", "SAFE"}:
            health.last_success_at = now
            health.consecutive_failures = 0
            health.last_error = None
        elif status in {"DEGRADED", "ACTION_REQUIRED", "FAILED", "UNSAFE"}:
            health.consecutive_failures += 1
            health.last_error = message
        health.metadata.update(metadata)

    async def restore_dependency(
        self,
        name: str,
        status: str,
        *,
        last_success_at: datetime,
        message: str | None = None,
        **metadata: Any,
    ) -> None:
        now = datetime.now(UTC)
        health = self._dependencies.setdefault(
            name,
            DependencyHealth(name=name, status=status),
        )
        health.status = status
        health.message = message
        health.last_success_at = last_success_at
        health.updated_at = now
        health.consecutive_failures = int(status == "DEGRADED")
        health.last_error = message if status == "DEGRADED" else None
        health.metadata.update(metadata)

    async def worker(self, name: str) -> dict[str, Any]:
        return asdict(self._workers.setdefault(name, WorkerHealth(name=name)))

    async def snapshot(self) -> dict[str, Any]:
        observed_at = datetime.now(UTC)
        workers = {name: asdict(value) for name, value in self._workers.items()}
        dependencies = {
            name: _dependency_payload(value, observed_at)
            for name, value in self._dependencies.items()
        }
        return {
            "overall": _overall_status(dependencies),
            "workers": workers,
            "dependencies": dependencies,
            "observed_at": observed_at,
        }


def _dependency_payload(health: DependencyHealth, observed_at: datetime) -> dict[str, Any]:
    payload = asdict(health)
    freshness_at = health.last_message_at if health.requires_message else health.last_success_at
    payload["age_seconds"] = (
        max((observed_at - freshness_at).total_seconds(), 0.0) if freshness_at is not None else None
    )
    if health.requires_message:
        if health.last_message_at is None and payload["status"] == "READY":
            payload["status"] = "UNKNOWN"
            payload["message"] = "connected without a business message"
        elif (
            health.max_message_age_seconds is not None
            and payload["age_seconds"] is not None
            and payload["age_seconds"] > health.max_message_age_seconds
            and payload["status"] == "READY"
        ):
            payload["status"] = "DEGRADED"
            payload["message"] = "business messages are stale"
    return payload


def _overall_status(dependencies: dict[str, dict[str, Any]]) -> str:
    database = dependencies.get("DATABASE", {}).get("status")
    if database not in {"READY"}:
        return "ACTION_REQUIRED"
    ai_statuses = [
        dependencies[name].get("status")
        for name in ("GPT", "CLAUDE", "GEMINI", "DEEPSEEK", "KIMI")
        if name in dependencies
    ]
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
