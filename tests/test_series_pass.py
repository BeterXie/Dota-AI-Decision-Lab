import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.auth.models import UserAccountRecord
from app.billing.paddle import paddle_signature_for_test
from app.db import Base
from app.entitlements import (
    AI_DECISIONS_ENTITLEMENT,
    REALTIME_NOTIFICATIONS_ENTITLEMENT,
    EntitlementService,
)
from app.models import CanonicalSeries, CanonicalTeam
from app.promotions.models import SeriesPassPurchaseRecord
from app.promotions.paddle_series import PaddleSeriesPassService

_SECRET = "pdl_series_test_webhook_secret_long_enough"
_PRICE = "pri_series_pass"


async def _fixture():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime.now(UTC).replace(microsecond=0)
    async with factory.begin() as session:
        team_a = CanonicalTeam(name="Alpha")
        team_b = CanonicalTeam(name="Beta")
        team_c = CanonicalTeam(name="Gamma")
        session.add_all([team_a, team_b, team_c])
        await session.flush()
        series = CanonicalSeries(team_a_id=team_a.id, team_b_id=team_b.id, best_of=3, scheduled_at=now)
        other_series = CanonicalSeries(
            team_a_id=team_a.id,
            team_b_id=team_c.id,
            best_of=3,
            scheduled_at=now,
        )
        user = UserAccountRecord(
            email="series@example.com",
            email_verified_at=now,
            last_login_at=now,
            created_at=now,
        )
        session.add_all([series, other_series, user])
        await session.flush()
        series_id = series.id
        other_series_id = other_series.id
        user_id = user.id
        session.add(
            SeriesPassPurchaseRecord(
                user_id=user_id,
                provider="paddle",
                transaction_ref="txn_series",
                customer_ref="ctm_series",
                canonical_series_id=series_id,
                price_ref=_PRICE,
                status="PENDING",
                payment_blocked=False,
                created_at=now,
                updated_at=now,
            )
        )
    service = PaddleSeriesPassService(
        factory,
        api_key="pdl_sdbx_test",
        webhook_secret=_SECRET,
        api_base_url="https://sandbox-api.paddle.com",
        price_id=_PRICE,
        access_days=3,
        webhook_tolerance_seconds=5,
    )
    return engine, factory, service, user_id, series_id, other_series_id, now


def _body(*, event_id: str, event_type: str, occurred_at: datetime, data: dict) -> bytes:
    return json.dumps(
        {
            "event_id": event_id,
            "event_type": event_type,
            "occurred_at": occurred_at.isoformat().replace("+00:00", "Z"),
            "data": data,
        },
        separators=(",", ":"),
    ).encode()


async def _deliver(service: PaddleSeriesPassService, body: bytes, *, now: datetime):
    return await service.process_webhook(
        raw_body=body,
        signature_header=paddle_signature_for_test(
            body,
            secret=_SECRET,
            timestamp=int(now.timestamp()),
        ),
        now=now,
    )


@pytest.mark.asyncio
async def test_series_pass_grants_only_purchased_series_and_refund_revokes() -> None:
    engine, factory, service, user_id, series_id, other_series_id, now = await _fixture()
    entitlements = EntitlementService(factory)
    try:
        purchase = _body(
            event_id="evt_series_paid",
            event_type="transaction.completed",
            occurred_at=now,
            data={
                "id": "txn_series",
                "customer_id": "ctm_series",
                "status": "completed",
                "items": [{"price": {"id": _PRICE}}],
                "custom_data": {
                    "dota_user_id": str(user_id),
                    "dota_offer": "series_pass",
                },
            },
        )
        first = await _deliver(service, purchase, now=now)
        duplicate = await _deliver(service, purchase, now=now)
        assert first.activated is True
        assert duplicate.duplicate is True
        assert await entitlements.active_entitlements(user_id, now=now) == ()
        for entitlement in (AI_DECISIONS_ENTITLEMENT, REALTIME_NOTIFICATIONS_ENTITLEMENT):
            assert (
                await entitlements.has_resource_entitlement(
                    user_id,
                    entitlement,
                    canonical_series_id=series_id,
                    now=now + timedelta(hours=1),
                )
                is True
            )
            assert (
                await entitlements.has_resource_entitlement(
                    user_id,
                    entitlement,
                    canonical_series_id=other_series_id,
                    now=now + timedelta(hours=1),
                )
                is False
            )

        refunded_at = now + timedelta(hours=2)
        refund = _body(
            event_id="evt_series_refund",
            event_type="adjustment.updated",
            occurred_at=refunded_at,
            data={
                "id": "adj_series",
                "action": "refund",
                "type": "full",
                "status": "approved",
                "transaction_id": "txn_series",
            },
        )
        result = await _deliver(service, refund, now=refunded_at)
        assert result.revoked is True
        assert (
            await entitlements.has_resource_entitlement(
                user_id,
                AI_DECISIONS_ENTITLEMENT,
                canonical_series_id=series_id,
                now=refunded_at,
            )
            is False
        )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_payment_block_prevents_later_completed_event_from_regranting() -> None:
    engine, factory, service, user_id, series_id, _, now = await _fixture()
    entitlements = EntitlementService(factory)
    try:
        refund = _body(
            event_id="evt_block_first",
            event_type="adjustment.updated",
            occurred_at=now,
            data={
                "id": "adj_block",
                "action": "chargeback",
                "type": "full",
                "status": "approved",
                "transaction_id": "txn_series",
            },
        )
        await _deliver(service, refund, now=now)

        later = now + timedelta(minutes=1)
        purchase = _body(
            event_id="evt_late_completed",
            event_type="transaction.completed",
            occurred_at=later,
            data={
                "id": "txn_series",
                "customer_id": "ctm_series",
                "status": "completed",
                "items": [{"price": {"id": _PRICE}}],
                "custom_data": {
                    "dota_user_id": str(user_id),
                    "dota_offer": "series_pass",
                },
            },
        )
        result = await _deliver(service, purchase, now=later)
        assert result.activated is False
        assert (
            await entitlements.has_resource_entitlement(
                user_id,
                AI_DECISIONS_ENTITLEMENT,
                canonical_series_id=series_id,
                now=later,
            )
            is False
        )
    finally:
        await engine.dispose()
