from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.auth.models import UserAccountRecord
from app.db import Base
from app.entitlements import (
    AI_DECISIONS_ENTITLEMENT,
    REALTIME_NOTIFICATIONS_ENTITLEMENT,
    EntitlementService,
)


@pytest.mark.asyncio
async def test_entitlements_respect_status_start_and_expiry() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime.now(UTC)
    async with factory.begin() as session:
        user = UserAccountRecord(
            email="pro@example.com",
            email_verified_at=now,
            last_login_at=now,
            created_at=now,
        )
        session.add(user)
        await session.flush()
        user_id = user.id

    service = EntitlementService(factory)
    try:
        assert await service.active_entitlements(user_id, now=now) == ()
        await service.grant(user_id, AI_DECISIONS_ENTITLEMENT, source="test")
        assert await service.has_entitlement(user_id, AI_DECISIONS_ENTITLEMENT, now=now)

        await service.grant(
            user_id,
            REALTIME_NOTIFICATIONS_ENTITLEMENT,
            source="future",
            starts_at=now + timedelta(hours=1),
        )
        assert not await service.has_entitlement(
            user_id,
            REALTIME_NOTIFICATIONS_ENTITLEMENT,
            now=now,
        )

        await service.grant(
            user_id,
            REALTIME_NOTIFICATIONS_ENTITLEMENT,
            source="expired",
            expires_at=now - timedelta(seconds=1),
        )
        assert not await service.has_entitlement(
            user_id,
            REALTIME_NOTIFICATIONS_ENTITLEMENT,
            now=now,
        )

        await service.revoke(user_id, AI_DECISIONS_ENTITLEMENT, source="test")
        assert not await service.has_entitlement(user_id, AI_DECISIONS_ENTITLEMENT, now=now)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_development_allowlist_grants_all_premium_entitlements() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime.now(UTC)
    async with factory.begin() as session:
        user = UserAccountRecord(
            email="owner@example.com",
            email_verified_at=now,
            last_login_at=now,
            created_at=now,
        )
        session.add(user)
        await session.flush()
        user_id = user.id

    service = EntitlementService(factory)
    try:
        active = await service.ensure_development_grants(
            user_id,
            "owner@example.com",
            ("OWNER@example.com",),
        )
        assert active == (AI_DECISIONS_ENTITLEMENT, REALTIME_NOTIFICATIONS_ENTITLEMENT)
    finally:
        await engine.dispose()
