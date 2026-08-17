from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.auth.models import UserAccountRecord
from app.db import Base
from app.entitlements import (
    ACCESS_SCOPE_MAP,
    ACCESS_SCOPE_SERIES,
    AI_DECISIONS_ENTITLEMENT,
    REALTIME_NOTIFICATIONS_ENTITLEMENT,
    EntitlementService,
)


async def _fixture():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime.now(UTC).replace(microsecond=0)
    async with factory.begin() as session:
        user = UserAccountRecord(
            email="scoped@example.com",
            email_verified_at=now,
            last_login_at=now,
            created_at=now,
        )
        session.add(user)
        await session.flush()
        user_id = user.id
    return engine, factory, user_id, now


@pytest.mark.asyncio
async def test_series_grant_is_resource_scoped_without_becoming_global_pro() -> None:
    engine, factory, user_id, now = await _fixture()
    series_id = uuid4()
    other_series_id = uuid4()
    service = EntitlementService(factory)
    try:
        await service.grant(
            user_id,
            AI_DECISIONS_ENTITLEMENT,
            source="test:series",
            scope_type=ACCESS_SCOPE_SERIES,
            scope_ref=series_id,
            expires_at=now + timedelta(days=3),
        )

        assert await service.active_entitlements(user_id, now=now) == ()
        assert (
            await service.has_entitlement(user_id, AI_DECISIONS_ENTITLEMENT, now=now)
            is False
        )
        assert (
            await service.has_resource_entitlement(
                user_id,
                AI_DECISIONS_ENTITLEMENT,
                canonical_series_id=series_id,
                now=now,
            )
            is True
        )
        assert (
            await service.has_resource_entitlement(
                user_id,
                AI_DECISIONS_ENTITLEMENT,
                canonical_series_id=other_series_id,
                now=now,
            )
            is False
        )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_global_grant_covers_every_resource_and_map_grant_only_exact_map() -> None:
    engine, factory, user_id, now = await _fixture()
    service = EntitlementService(factory)
    map_id = uuid4()
    other_map_id = uuid4()
    try:
        await service.grant(
            user_id,
            REALTIME_NOTIFICATIONS_ENTITLEMENT,
            source="test:global",
        )
        assert (
            await service.access_scope(
                user_id,
                REALTIME_NOTIFICATIONS_ENTITLEMENT,
                canonical_series_id=uuid4(),
                canonical_map_id=map_id,
                now=now,
            )
            == "GLOBAL"
        )

        await service.grant(
            user_id,
            AI_DECISIONS_ENTITLEMENT,
            source="test:map",
            scope_type=ACCESS_SCOPE_MAP,
            scope_ref=map_id,
        )
        assert (
            await service.access_scope(
                user_id,
                AI_DECISIONS_ENTITLEMENT,
                canonical_map_id=map_id,
                now=now,
            )
            == "MAP"
        )
        assert (
            await service.has_resource_entitlement(
                user_id,
                AI_DECISIONS_ENTITLEMENT,
                canonical_map_id=other_map_id,
                now=now,
            )
            is False
        )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_same_source_cannot_be_moved_to_another_access_scope() -> None:
    engine, factory, user_id, _ = await _fixture()
    service = EntitlementService(factory)
    try:
        await service.grant(
            user_id,
            AI_DECISIONS_ENTITLEMENT,
            source="immutable-source",
            scope_type=ACCESS_SCOPE_SERIES,
            scope_ref=uuid4(),
        )
        with pytest.raises(ValueError, match="cannot move"):
            await service.grant(
                user_id,
                AI_DECISIONS_ENTITLEMENT,
                source="immutable-source",
                scope_type=ACCESS_SCOPE_SERIES,
                scope_ref=uuid4(),
            )
    finally:
        await engine.dispose()
