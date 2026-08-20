from datetime import UTC, datetime
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.auth import AuthenticatedUser
from app.auth.models import UserAccountRecord
from app.db import Base
from app.entitlements import (
    ACCESS_SCOPE_SERIES,
    REALTIME_NOTIFICATIONS_ENTITLEMENT,
    EntitlementService,
)
from app.models import CanonicalMap, CanonicalSeries, CanonicalTeam, DecisionSnapshotRecord
from app.notifications.center import (
    CHANNEL_EMAIL,
    CHANNEL_QQ,
    EVENT_AI_DECISION,
    NotificationBindingConflict,
    qq_destination_key,
)
from app.notifications.models import NotificationDeliveryRecord
from app.notifications.secure_center import NotificationCenterService
from app.runtime.health import HealthRegistry
from app.web import create_app


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


async def _snapshot(factory, *, suffix: str):
    now = datetime.now(UTC)
    async with factory.begin() as session:
        team_a = CanonicalTeam(name=f"Alpha {suffix}")
        team_b = CanonicalTeam(name=f"Beta {suffix}")
        session.add_all([team_a, team_b])
        await session.flush()
        series = CanonicalSeries(
            team_a_id=team_a.id,
            team_b_id=team_b.id,
            best_of=3,
            scheduled_at=now,
        )
        session.add(series)
        await session.flush()
        canonical_map = CanonicalMap(
            series_id=series.id,
            map_number=1,
            scheduled_at=now,
        )
        session.add(canonical_map)
        await session.flush()
        snapshot = DecisionSnapshotRecord(
            id=uuid4(),
            canonical_map_id=canonical_map.id,
            decision_at=now,
            created_at=now,
            mode="LIVE_BASIC",
            canonical_payload={},
            snapshot_hash=f"snapshot-{suffix}-{uuid4().hex}",
        )
        session.add(snapshot)
        await session.flush()
        return series.id, canonical_map.id, snapshot.id


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
        assert len(code.replace("-", "")) == 24
        assert len(code.split("-")) == 6
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
async def test_pairing_api_returns_channel_contact_metadata() -> None:
    engine, factory = await _factory()
    try:
        user_id, verified_at = await _user(factory, "pairing@example.com")
        await EntitlementService(factory).grant(
            user_id,
            REALTIME_NOTIFICATIONS_ENTITLEMENT,
            source="test",
        )
        now = datetime.now(UTC)
        auth_user = AuthenticatedUser(
            id=user_id,
            email="pairing@example.com",
            email_verified_at=verified_at,
            display_name=None,
            avatar_url=None,
            created_at=now,
        )

        class AuthStub:
            async def authenticate(self, token: str | None):
                return auth_user if token == "test-session" else None

        app = create_app(
            factory,
            HealthRegistry(),
            frontend_dist=None,
            auth_enabled=True,
            auth_cookie_secure=False,
            auth_service=AuthStub(),
            qq_pairing_link_factory=lambda code: _share_link(code),
            qq_contact_url="https://qq.example/contact",
            wechat_contact_url="https://wechat.example/contact",
        )

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            cookies={"dota_session": "test-session"},
        ) as client:
            qq = await client.post("/api/notifications/pairing/qq")
            wechat = await client.post("/api/notifications/pairing/wechat")

        assert qq.status_code == 200
        assert qq.json()["pairing_mode"] == "QQ_SHARE_LINK"
        assert qq.json()["share_url"].startswith("https://qq.example/")
        assert qq.json()["contact_url"] == "https://qq.example/contact"
        assert wechat.status_code == 200
        assert wechat.json()["pairing_mode"] == "WECHAT_CONTACT_LINK"
        assert wechat.json()["contact_url"] == "https://wechat.example/contact"
        assert wechat.json()["share_url"] is None
    finally:
        await engine.dispose()


async def _share_link(code: str) -> str:
    return f"https://qq.example/invite/{code}"


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
            assert (
                await session.scalar(select(func.count()).select_from(NotificationDeliveryRecord))
                == 1
            )

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


@pytest.mark.asyncio
async def test_series_grant_fans_out_only_for_covered_series_and_rechecks_before_send() -> None:
    engine, factory = await _factory()
    try:
        user_id, verified_at = await _user(factory, "series-pass@example.com")
        covered_series_id, _, covered_snapshot_id = await _snapshot(factory, suffix="covered")
        _, _, other_snapshot_id = await _snapshot(factory, suffix="other")
        entitlements = EntitlementService(factory)
        source = "billing:paddle-series:test"
        await entitlements.grant(
            user_id,
            REALTIME_NOTIFICATIONS_ENTITLEMENT,
            source=source,
            scope_type=ACCESS_SCOPE_SERIES,
            scope_ref=covered_series_id,
        )
        center = NotificationCenterService(factory)
        await center.ensure_email_binding(
            user_id=user_id,
            email="series-pass@example.com",
            verified_at=verified_at,
        )

        async with factory.begin() as session:
            covered = await center.ensure_deliveries(
                session,
                channel=CHANNEL_EMAIL,
                snapshot_id=covered_snapshot_id,
                decision_ids=[uuid4()],
            )
            unrelated = await center.ensure_deliveries(
                session,
                channel=CHANNEL_EMAIL,
                snapshot_id=other_snapshot_id,
                decision_ids=[uuid4()],
            )
        assert len(covered) == 1
        assert unrelated == []

        await entitlements.revoke(
            user_id,
            REALTIME_NOTIFICATIONS_ENTITLEMENT,
            source=source,
        )
        assert await center.start_delivery(covered[0].id) is None
        delivery, _ = await center.delivery_receipt(covered[0].id)
        assert delivery.status == "CANCELLED"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_disabled_account_is_removed_from_fanout_and_cancels_queued_delivery() -> None:
    engine, factory = await _factory()
    try:
        user_id, verified_at = await _user(factory, "disabled@example.com")
        entitlements = EntitlementService(factory)
        await entitlements.grant(
            user_id,
            REALTIME_NOTIFICATIONS_ENTITLEMENT,
            source="test",
        )
        center = NotificationCenterService(factory)
        await center.ensure_email_binding(
            user_id=user_id,
            email="disabled@example.com",
            verified_at=verified_at,
        )
        snapshot_id = uuid4()
        decision_ids = [uuid4()]
        async with factory.begin() as session:
            deliveries = await center.ensure_deliveries(
                session,
                channel=CHANNEL_EMAIL,
                snapshot_id=snapshot_id,
                decision_ids=decision_ids,
            )
        assert len(deliveries) == 1

        async with factory.begin() as session:
            user = await session.get(UserAccountRecord, user_id)
            assert user is not None
            user.disabled_at = datetime.now(UTC)

        async with factory() as session:
            assert await center.eligible_bindings(session, CHANNEL_EMAIL) == []
        assert await center.start_delivery(deliveries[0].id) is None
        delivery, _ = await center.delivery_receipt(deliveries[0].id)
        assert delivery.status == "CANCELLED"
    finally:
        await engine.dispose()
