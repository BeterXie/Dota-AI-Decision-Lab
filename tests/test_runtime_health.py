from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.main import _restore_email_health
from app.notifications.models import NotificationDeliveryRecord
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


@pytest.mark.asyncio
async def test_email_health_restores_from_current_user_delivery_record() -> None:
    sent_at = datetime.now(UTC) - timedelta(minutes=2)
    latest = SimpleNamespace(
        id=uuid4(),
        status="SENT",
        sent_at=sent_at,
        last_error=None,
    )

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args) -> None:
            return None

        async def scalar(self, statement):
            assert statement.column_descriptions[0]["entity"] is NotificationDeliveryRecord
            assert "EMAIL" in statement.compile().params.values()
            return latest

    health = HealthRegistry()
    await _restore_email_health(
        health,
        session_factory=_Session,
        configured=True,
    )

    dependency = (await health.snapshot())["dependencies"]["EMAIL"]
    assert dependency["status"] == "READY"
    assert dependency["last_success_at"] == sent_at
    assert dependency["metadata"]["recipient_count"] == 1
    assert dependency["metadata"]["notification_id"] == str(latest.id)
