from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.auth.models import UserAccountRecord
from app.billing import (
    BILLING_ACCESS_ACTIVE,
    BILLING_ACCESS_INACTIVE,
    PRO_PLAN,
    BillingEntitlementService,
    BillingEventConflict,
)
from app.billing.models import BillingEventRecord, BillingSubscriptionRecord
from app.db import Base
from app.entitlements import AI_DECISIONS_ENTITLEMENT, PREMIUM_ENTITLEMENTS, EntitlementService
from app.entitlements.models import UserEntitlementRecord


@pytest.mark.asyncio
async def test_billing_events_idempotently_grant_and_revoke_subscription_source() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime.now(UTC)
    try:
        async with factory.begin() as session:
            user = UserAccountRecord(
                email="subscriber@example.com",
                email_verified_at=now,
                last_login_at=now,
                created_at=now,
            )
            session.add(user)
            await session.flush()
            user_id = user.id

        # A non-billing entitlement source must survive subscription cancellation.
        await EntitlementService(factory).grant(
            user_id,
            AI_DECISIONS_ENTITLEMENT,
            source="manual-promo",
        )

        service = BillingEntitlementService(factory)
        period_end = now + timedelta(days=30)
        activated = await service.apply_subscription_event(
            provider="examplepay",
            event_ref="evt-1",
            user_id=user_id,
            subscription_ref="sub-123",
            customer_ref="cus-123",
            plan_key=PRO_PLAN,
            access_state=BILLING_ACCESS_ACTIVE,
            provider_status="paid",
            current_period_end=period_end,
        )
        assert activated.duplicate is False
        assert set(activated.active_entitlements) == set(PREMIUM_ENTITLEMENTS)

        duplicate = await service.apply_subscription_event(
            provider="examplepay",
            event_ref="evt-1",
            user_id=user_id,
            subscription_ref="sub-123",
            customer_ref="cus-123",
            plan_key=PRO_PLAN,
            access_state=BILLING_ACCESS_ACTIVE,
            provider_status="paid",
            current_period_end=period_end,
        )
        assert duplicate.duplicate is True

        with pytest.raises(BillingEventConflict):
            await service.apply_subscription_event(
                provider="examplepay",
                event_ref="evt-1",
                user_id=user_id,
                subscription_ref="sub-123",
                plan_key=PRO_PLAN,
                access_state=BILLING_ACCESS_INACTIVE,
                provider_status="canceled",
            )

        cancelled = await service.apply_subscription_event(
            provider="examplepay",
            event_ref="evt-2",
            user_id=user_id,
            subscription_ref="sub-123",
            plan_key=PRO_PLAN,
            access_state=BILLING_ACCESS_INACTIVE,
            provider_status="canceled",
        )
        # Manual promo remains; realtime notification access supplied only by the
        # billing subscription is revoked.
        assert cancelled.active_entitlements == (AI_DECISIONS_ENTITLEMENT,)

        async with factory() as session:
            event_count = await session.scalar(select(func.count(BillingEventRecord.id)))
            subscriptions = list((await session.scalars(select(BillingSubscriptionRecord))).all())
            billing_entitlements = list(
                (
                    await session.scalars(
                        select(UserEntitlementRecord).where(
                            UserEntitlementRecord.user_id == user_id,
                            UserEntitlementRecord.source.like("billing:%"),
                        )
                    )
                ).all()
            )
        assert event_count == 2
        assert len(subscriptions) == 1
        assert subscriptions[0].access_state == BILLING_ACCESS_INACTIVE
        assert {item.entitlement for item in billing_entitlements} == set(PREMIUM_ENTITLEMENTS)
        assert all(item.status == "REVOKED" for item in billing_entitlements)
    finally:
        await engine.dispose()
