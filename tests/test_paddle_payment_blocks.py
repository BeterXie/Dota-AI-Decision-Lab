import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.auth.models import UserAccountRecord
from app.billing.models import BillingCheckoutRecord, BillingSubscriptionRecord
from app.billing.paddle import PaddleBillingGateway, PaddleOffer, paddle_signature_for_test
from app.db import Base
from app.entitlements import EntitlementService

_SECRET = "pdl_ntfset_test_payment_block_secret"
_PRICE = "pri_test_monthly_block"


def _body(
    *,
    event_id: str,
    event_type: str,
    occurred_at: datetime,
    user_id,
    data: dict,
) -> bytes:
    payload = {
        "event_id": event_id,
        "event_type": event_type,
        "occurred_at": occurred_at.isoformat().replace("+00:00", "Z"),
        "data": {
            **data,
            "custom_data": {
                "dota_ai_billing": "dota-ai-billing-v1",
                "dota_user_id": str(user_id),
                "dota_plan": "PRO",
                "dota_offer": "pro_monthly",
            },
        },
    }
    return json.dumps(payload, separators=(",", ":")).encode()


async def _deliver(gateway: PaddleBillingGateway, body: bytes, now: datetime):
    return await gateway.process_webhook(
        raw_body=body,
        signature_header=paddle_signature_for_test(
            body,
            secret=_SECRET,
            timestamp=int(now.timestamp()),
        ),
        now=now,
    )


@pytest.mark.asyncio
async def test_chargeback_block_survives_later_active_subscription_and_reversal_events() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime.now(UTC).replace(microsecond=0)
    offer = PaddleOffer(
        key="pro_monthly",
        label="Pro Monthly",
        price_id=_PRICE,
        recurring=True,
        grant_days=None,
        supports_alipay=True,
        supports_wechat_pay=False,
    )
    gateway = PaddleBillingGateway(
        session_factory=factory,
        api_key="pdl_sdbx_apikey_test",
        webhook_secret=_SECRET,
        api_base_url="https://sandbox-api.paddle.com",
        offers=(offer,),
    )
    try:
        async with factory.begin() as session:
            user = UserAccountRecord(
                email="dispute@example.com",
                email_verified_at=now,
                last_login_at=now,
                created_at=now,
            )
            session.add(user)
            await session.flush()
            user_id = user.id
            session.add(
                BillingCheckoutRecord(
                    user_id=user_id,
                    provider="paddle",
                    checkout_ref="txn_dispute",
                    customer_ref="ctm_dispute",
                    offer_key=offer.key,
                    price_ref=offer.price_id,
                    plan_key="PRO",
                    recurring=True,
                    grant_days=None,
                    status="PENDING",
                    created_at=now,
                    updated_at=now,
                )
            )

        period_end = now + timedelta(days=30)
        purchase = _body(
            event_id="evt_purchase_dispute",
            event_type="transaction.completed",
            occurred_at=now,
            user_id=user_id,
            data={
                "id": "txn_dispute",
                "customer_id": "ctm_dispute",
                "subscription_id": "sub_dispute",
                "status": "completed",
                "items": [{"price": {"id": _PRICE}}],
                "billing_period": {
                    "starts_at": now.isoformat(),
                    "ends_at": period_end.isoformat(),
                },
            },
        )
        await _deliver(gateway, purchase, now)
        assert await EntitlementService(factory).active_entitlements(user_id)

        chargeback_at = now + timedelta(minutes=1)
        chargeback = _body(
            event_id="evt_chargeback",
            event_type="adjustment.updated",
            occurred_at=chargeback_at,
            user_id=user_id,
            data={
                "id": "adj_chargeback",
                "action": "chargeback",
                "type": "full",
                "status": "approved",
                "transaction_id": "txn_dispute",
                "subscription_id": "sub_dispute",
            },
        )
        await _deliver(gateway, chargeback, chargeback_at)
        assert await EntitlementService(factory).active_entitlements(user_id) == ()

        active_at = now + timedelta(minutes=2)
        active_update = _body(
            event_id="evt_active_after_chargeback",
            event_type="subscription.updated",
            occurred_at=active_at,
            user_id=user_id,
            data={
                "id": "sub_dispute",
                "customer_id": "ctm_dispute",
                "status": "active",
                "items": [{"price": {"id": _PRICE}}],
                "current_billing_period": {
                    "starts_at": now.isoformat(),
                    "ends_at": period_end.isoformat(),
                },
            },
        )
        await _deliver(gateway, active_update, active_at)
        assert await EntitlementService(factory).active_entitlements(user_id) == ()

        reverse_at = now + timedelta(minutes=3)
        reversal = _body(
            event_id="evt_chargeback_reverse",
            event_type="adjustment.updated",
            occurred_at=reverse_at,
            user_id=user_id,
            data={
                "id": "adj_chargeback_reverse",
                "action": "chargeback_reverse",
                "type": "full",
                "status": "approved",
                "transaction_id": "txn_dispute",
                "subscription_id": "sub_dispute",
            },
        )
        reversal_result = await _deliver(gateway, reversal, reverse_at)
        assert reversal_result.ignored is True
        assert await EntitlementService(factory).active_entitlements(user_id) == ()

        async with factory() as session:
            subscription = await session.scalar(
                select(BillingSubscriptionRecord).where(
                    BillingSubscriptionRecord.subscription_ref == "sub_dispute"
                )
            )
            assert subscription is not None
            assert subscription.access_state == "INACTIVE"
            assert subscription.provider_status == "blocked:chargeback:approved"
    finally:
        await engine.dispose()
