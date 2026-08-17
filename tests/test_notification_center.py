from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.auth.models import UserAccountRecord
from app.db import Base
from app.entitlements import REALTIME_NOTIFICATIONS_ENTITLEMENT, EntitlementService
from app.notifications.center import (
    CHANNEL_EMAIL,
    CHANNEL_QQ,
    EVENT_AI_DECISION,
    NotificationBindingConflict,
    NotificationCenterService,
    qq_destination_key,
)
from app.notifications.models import NotificationDeliveryRecord


async def _factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _user(factory, email: str):
    now = datetime.now(UTC)
    async with factory.begin() as session:
        user = UserAccountRecord(
            email=email,
            email_verified_at=now,
            last_login_at=now,
            created_at=now,
        )
        session.add(user)
        await session.flush()
        return user.id, now


@pytest.mark.asyncio
async def test_verified_bindings_require_realtime_entitlement_and_preference() -> None:
    engine, factory = await _factory()
    try:
        pro_id, verified_at = await _user(factory, "pro@example.com")
        free_id, free_verified_at = await _user(factory, "free@example.com")
        center = NotificationCenterService(factory)
        await center.ensure_email_binding(
            user_id=pro_id,
            email="pro@example.com",
            verified_at=verified_at,
        )
        await center.ensure_email_binding(
            user_id=free_id,
            email="free@example.com",
            verified_at=free_verified_at,
        )
        await EntitlementService(factory).grant(
            pro_id,
            REALTIME_NOTIFICATIONS_ENTITLEMENT,
            source="test",
        )

        async with factory() as session:
            eligible = await center.eligible_bindings(session, CHANNEL_EMAIL)
        assert [item.user_id for item in eligible] == [pro_id]

        await center.set_preference(pro_id, CHANNEL_EMAIL, enabled=False)
        async with factory() as session:
            assert await center.eligible_bindings(session, CHANNEL_EMAIL) == []
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_pairing_code_verifies_qq_destination_and_prevents_cross_account_claim() -> None:
    engine, factory = await _factory()
    try:
        first_id, _ = await _user(factory, "first@example.com")
        second_id, _ = await _user(factory, "second@example.com")
        center = NotificationCenterService(factory)
        code, _ = await center.create_pairing_code(first_id, CHANNEL_QQ)
        binding = await center.consume_pairing_code(
            channel=CHANNEL_QQ,
            code=code,
            destination_key=qq_destination_key("c2c", "openid-1"),
            destination={"scope": "c2c", "target_id": "openid-1"},
            label="My QQ",
        )
        assert binding.user_id == first_id
        assert binding.status == "ACTIVE"

        second_code, _ = await center.create_pairing_code(second_id, CHANNEL_QQ)
        with pytest.raises(NotificationBindingConflict):
            await center.consume_pairing_code(
                channel=CHANNEL_QQ,
                code=second_code,
                destination_key=qq_destination_key("c2c", "openid-1"),
                destination={"scope": "c2c", "target_id": "openid-1"},
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_delivery_is_idempotent_and_rechecks_entitlement_before_send() -> None:
    engine, factory = await _factory()
    try:
        user_id, verified_at = await _user(factory, "pro@example.com")
        entitlements = EntitlementService(factory)
        await entitlements.grant(
            user_id,
            REALTIME_NOTIFICATIONS_ENTITLEMENT,
            source="test",
        )
        center = NotificationCenterService(factory)
        binding = await center.ensure_email_binding(
            user_id=user_id,
            email="pro@example.com",
            verified_at=verified_at,
        )
        snapshot_id = uuid4()
        decision_ids = [uuid4(), uuid4()]
        async with factory.begin() as session:
            first = await center.ensure_deliveries(
                session,
                channel=CHANNEL_EMAIL,
                snapshot_id=snapshot_id,
                decision_ids=decision_ids,
                event_type=EVENT_AI_DECISION,
            )
            second = await center.ensure_deliveries(
                session,
                channel=CHANNEL_EMAIL,
                snapshot_id=snapshot_id,
                decision_ids=decision_ids,
                event_type=EVENT_AI_DECISION,
            )
        assert [item.id for item in first] == [item.id for item in second]
        async with factory() as session:
            assert await session.scalar(select(func.count()).select_from(NotificationDeliveryRecord)) == 1

        await entitlements.revoke(
            user_id,
            REALTIME_NOTIFICATIONS_ENTITLEMENT,
            source="test",
        )
        assert await center.start_delivery(first[0].id) is None
        delivery, destination = await center.delivery_receipt(first[0].id)
        assert delivery.status == "CANCELLED"
        assert destination == {"email": "pro@example.com"}
        assert binding.user_id == user_id
    finally:
        await engine.dispose()
