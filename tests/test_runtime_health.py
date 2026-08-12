from datetime import UTC, datetime, timedelta

import pytest

from app.runtime.health import HealthRegistry


@pytest.mark.asyncio
async def test_socket_dependency_requires_a_fresh_business_message() -> None:
    health = HealthRegistry()
    await health.dependency("DATABASE", "READY")
    await health.dependency(
        "RAYBET_SOCKET",
        "READY",
        requires_message=True,
        max_message_age_seconds=30,
    )

    connected = await health.snapshot()

    assert connected["dependencies"]["RAYBET_SOCKET"]["status"] == "UNKNOWN"
    assert connected["dependencies"]["RAYBET_SOCKET"]["age_seconds"] is None
    assert connected["overall"] == "DEGRADED"

    await health.dependency(
        "RAYBET_SOCKET",
        "READY",
        business_message=True,
        requires_message=True,
        max_message_age_seconds=30,
    )
    fresh = await health.snapshot()
    assert fresh["dependencies"]["RAYBET_SOCKET"]["status"] == "READY"
    assert fresh["dependencies"]["RAYBET_SOCKET"]["age_seconds"] is not None


@pytest.mark.asyncio
async def test_stale_socket_message_degrades_readiness() -> None:
    health = HealthRegistry()
    await health.dependency("DATABASE", "READY")
    await health.dependency(
        "DLTV_SOCKET",
        "READY",
        business_message=True,
        requires_message=True,
        max_message_age_seconds=30,
    )
    health._dependencies["DLTV_SOCKET"].last_message_at = datetime.now(UTC) - timedelta(seconds=31)

    snapshot = await health.snapshot()
    dependency = snapshot["dependencies"]["DLTV_SOCKET"]

    assert dependency["status"] == "DEGRADED"
    assert dependency["age_seconds"] >= 31
    assert snapshot["overall"] == "DEGRADED"


@pytest.mark.asyncio
async def test_dependency_health_preserves_attempt_success_and_failure_state() -> None:
    health = HealthRegistry()
    await health.dependency("STRATZ", "READY", coverage=12)
    await health.dependency("STRATZ", "DEGRADED", message="timeout", coverage=12)

    dependency = (await health.snapshot())["dependencies"]["STRATZ"]

    assert dependency["last_attempt_at"] is not None
    assert dependency["last_success_at"] is not None
    assert dependency["last_message_at"] is None
    assert dependency["consecutive_failures"] == 1
    assert dependency["last_error"] == "timeout"
    assert dependency["metadata"]["coverage"] == 12


@pytest.mark.asyncio
async def test_dependency_health_restores_persisted_success_age() -> None:
    health = HealthRegistry()
    observed_success = datetime.now(UTC) - timedelta(minutes=5)
    await health.restore_dependency(
        "HISTORY",
        "READY",
        last_success_at=observed_success,
        maps_stored=120,
    )

    dependency = (await health.snapshot())["dependencies"]["HISTORY"]

    assert dependency["status"] == "READY"
    assert dependency["age_seconds"] >= 300
    assert dependency["metadata"]["maps_stored"] == 120


@pytest.mark.asyncio
async def test_all_registered_ai_providers_requiring_action_blocks_readiness() -> None:
    health = HealthRegistry()
    await health.dependency("DATABASE", "READY")
    for provider in ("GPT", "CLAUDE", "GEMINI", "DEEPSEEK", "KIMI"):
        await health.dependency(provider, "ACTION_REQUIRED")

    snapshot = await health.snapshot()

    assert snapshot["overall"] == "ACTION_REQUIRED"
