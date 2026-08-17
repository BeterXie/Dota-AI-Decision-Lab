import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.auth.models import UserAccountRecord
from app.billing.models import BillingCheckoutRecord, BillingSubscriptionRecord
from app.billing.paddle import (
    PaddleBillingGateway,
    PaddleCheckoutConflict,
    PaddleOffer,
    PaddleWebhookError,
    PaddleWebhookSignatureError,
    paddle_signature_for_test,
)
from app.db import Base
from app.entitlements import PREMIUM_ENTITLEMENTS, EntitlementService

_WEBHOOK_SECRET = "pdl_ntfset_test_secret_that_is_long_enough"
_PRICE_30D = "pri_test_pro_30d"
_PRICE_MONTHLY = "pri_test_pro_monthly"


def _offer_30d() -> PaddleOffer:
    return PaddleOffer(
        key="pro_30d",
        label="Pro 30-day Pass",
        price_id=_PRICE_30D,
        recurring=False,
        grant_days=30,
        supports_alipay=True,
        supports_wechat_pay=True,
    )


def _offer_monthly() -> PaddleOffer:
    return PaddleOffer(
        key="pro_monthly",
        label="Pro Monthly",
        price_id=_PRICE_MONTHLY,
        recurring=True,
        grant_days=None,
        supports_alipay=True,
        supports_wechat_pay=False,
    )


async def _fixture(*offers: PaddleOffer):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime.now(UTC).replace(microsecond=0)
    async with factory.begin() as session:
        user = UserAccountRecord(
            email="buyer@example.com",
            email_verified_at=now,
            last_login_at=now,
            created_at=now,
        )
        session.add(user)
        await session.flush()
        user_id = user.id
    gateway = PaddleBillingGateway(
        session_factory=factory,
        api_key="pdl_sdbx_apikey_test",
        webhook_secret=_WEBHOOK_SECRET,
        api_base_url="https://sandbox-api.paddle.com",
        offers=offers or (_offer_30d(),),
        webhook_tolerance_seconds=5,
    )
    return engine, factory, user_id, now, gateway


async def _seed_checkout(
    factory,
    *,
    user_id,
    offer: PaddleOffer,
    transaction_ref: str,
    customer_ref: str = "ctm_buyer",
) -> None:
    now = datetime.now(UTC)
    async with factory.begin() as session:
        session.add(
            BillingCheckoutRecord(
                user_id=user_id,
                provider="paddle",
                checkout_ref=transaction_ref,
                customer_ref=customer_ref,
                offer_key=offer.key,
                price_ref=offer.price_id,
                plan_key="PRO",
                recurring=offer.recurring,
                grant_days=offer.grant_days,
                status="PENDING",
                created_at=now,
                updated_at=now,
            )
        )


def _event(
    *,
    event_id: str,
    event_type: str,
    occurred_at: datetime,
    user_id,
    offer_key: str,
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
                "dota_offer": offer_key,
            },
        },
    }
    return json.dumps(payload, separators=(",", ":")).encode()


async def _deliver(gateway: PaddleBillingGateway, body: bytes, *, now: datetime):
    signature = paddle_signature_for_test(
        body,
        secret=_WEBHOOK_SECRET,
        timestamp=int(now.timestamp()),
    )
    return await gateway.process_webhook(
        raw_body=body,
        signature_header=signature,
        now=now,
    )


@pytest.mark.asyncio
async def test_one_time_completed_transaction_grants_fixed_term_pro_idempotently() -> None:
    offer = _offer_30d()
    engine, factory, user_id, now, gateway = await _fixture(offer)
    try:
        await _seed_checkout(
            factory,
            user_id=user_id,
            offer=offer,
            transaction_ref="txn_one_time",
        )
        body = _event(
            event_id="evt_one_time",
            event_type="transaction.completed",
            occurred_at=now,
            user_id=user_id,
            offer_key=offer.key,
            data={
                "id": "txn_one_time",
                "customer_id": "ctm_buyer",
                "subscription_id": None,
                "status": "completed",
                "items": [{"price": {"id": _PRICE_30D}}],
            },
        )
        first = await _deliver(gateway, body, now=now)
        duplicate = await _deliver(gateway, body, now=now)

        assert first.ignored is False
        assert first.duplicate is False
        assert set(first.active_entitlements) == set(PREMIUM_ENTITLEMENTS)
        assert duplicate.duplicate is True
        assert set(await EntitlementService(factory).active_entitlements(user_id, now=now)) == set(
            PREMIUM_ENTITLEMENTS
        )
        assert (
            await EntitlementService(factory).active_entitlements(
                user_id,
                now=now + timedelta(days=30, seconds=1),
            )
            == ()
        )
        async with factory() as session:
            checkout = await session.scalar(select(BillingCheckoutRecord))
            assert checkout is not None
            assert checkout.status == "COMPLETED"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_subscription_cancel_revokes_and_delayed_activation_cannot_restore_access() -> None:
    offer = _offer_monthly()
    engine, factory, user_id, now, gateway = await _fixture(offer)
    try:
        await _seed_checkout(
            factory,
            user_id=user_id,
            offer=offer,
            transaction_ref="txn_monthly",
        )
        period_end = now + timedelta(days=30)
        purchase = _event(
            event_id="evt_monthly_purchase",
            event_type="transaction.completed",
            occurred_at=now,
            user_id=user_id,
            offer_key=offer.key,
            data={
                "id": "txn_monthly",
                "customer_id": "ctm_buyer",
                "subscription_id": "sub_monthly",
                "status": "completed",
                "items": [{"price": {"id": _PRICE_MONTHLY}}],
                "billing_period": {
                    "starts_at": now.isoformat(),
                    "ends_at": period_end.isoformat(),
                },
            },
        )
        await _deliver(gateway, purchase, now=now)
        assert set(await EntitlementService(factory).active_entitlements(user_id)) == set(
            PREMIUM_ENTITLEMENTS
        )

        canceled_at = now + timedelta(minutes=2)
        canceled_body = _event(
            event_id="evt_canceled",
            event_type="subscription.canceled",
            occurred_at=canceled_at,
            user_id=user_id,
            offer_key=offer.key,
            data={
                "id": "sub_monthly",
                "customer_id": "ctm_buyer",
                "status": "canceled",
                "items": [{"price": {"id": _PRICE_MONTHLY}}],
                "current_billing_period": {
                    "starts_at": now.isoformat(),
                    "ends_at": period_end.isoformat(),
                },
            },
        )
        await _deliver(gateway, canceled_body, now=canceled_at)
        assert await EntitlementService(factory).active_entitlements(user_id) == ()

        delayed_body = _event(
            event_id="evt_delayed_active",
            event_type="subscription.activated",
            occurred_at=now + timedelta(minutes=1),
            user_id=user_id,
            offer_key=offer.key,
            data={
                "id": "sub_monthly",
                "customer_id": "ctm_buyer",
                "status": "active",
                "items": [{"price": {"id": _PRICE_MONTHLY}}],
                "current_billing_period": {
                    "starts_at": now.isoformat(),
                    "ends_at": period_end.isoformat(),
                },
            },
        )
        delayed = await _deliver(gateway, delayed_body, now=canceled_at)
        assert delayed.stale is True
        assert await EntitlementService(factory).active_entitlements(user_id) == ()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_full_approved_refund_revokes_one_time_pass_but_partial_refund_does_not() -> None:
    offer = _offer_30d()
    engine, factory, user_id, now, gateway = await _fixture(offer)
    try:
        await _seed_checkout(
            factory,
            user_id=user_id,
            offer=offer,
            transaction_ref="txn_refundable",
        )
        purchase = _event(
            event_id="evt_purchase",
            event_type="transaction.completed",
            occurred_at=now,
            user_id=user_id,
            offer_key=offer.key,
            data={
                "id": "txn_refundable",
                "customer_id": "ctm_buyer",
                "status": "completed",
                "items": [{"price": {"id": _PRICE_30D}}],
            },
        )
        await _deliver(gateway, purchase, now=now)

        partial_at = now + timedelta(minutes=1)
        partial = _event(
            event_id="evt_partial_refund",
            event_type="adjustment.updated",
            occurred_at=partial_at,
            user_id=user_id,
            offer_key=offer.key,
            data={
                "id": "adj_partial",
                "action": "refund",
                "type": "partial",
                "status": "approved",
                "transaction_id": "txn_refundable",
                "subscription_id": None,
            },
        )
        partial_result = await _deliver(gateway, partial, now=partial_at)
        assert partial_result.ignored is True
        assert set(await EntitlementService(factory).active_entitlements(user_id)) == set(
            PREMIUM_ENTITLEMENTS
        )

        refund_at = now + timedelta(minutes=2)
        refund = _event(
            event_id="evt_full_refund",
            event_type="adjustment.updated",
            occurred_at=refund_at,
            user_id=user_id,
            offer_key=offer.key,
            data={
                "id": "adj_full",
                "action": "refund",
                "type": "full",
                "status": "approved",
                "transaction_id": "txn_refundable",
                "subscription_id": None,
            },
        )
        result = await _deliver(gateway, refund, now=refund_at)
        assert result.ignored is False
        assert await EntitlementService(factory).active_entitlements(user_id) == ()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_signed_unmapped_transaction_cannot_grant_an_arbitrary_user() -> None:
    offer = _offer_30d()
    engine, factory, user_id, now, gateway = await _fixture(offer)
    try:
        body = _event(
            event_id="evt_unmapped",
            event_type="transaction.completed",
            occurred_at=now,
            user_id=user_id,
            offer_key=offer.key,
            data={
                "id": "txn_not_created_by_server",
                "customer_id": "ctm_attacker",
                "status": "completed",
                "items": [{"price": {"id": _PRICE_30D}}],
            },
        )
        result = await _deliver(gateway, body, now=now)
        assert result.ignored is True
        assert await EntitlementService(factory).active_entitlements(user_id) == ()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_signature_replay_and_checkout_price_mismatch_fail_closed() -> None:
    offer = _offer_30d()
    engine, factory, user_id, now, gateway = await _fixture(offer)
    try:
        await _seed_checkout(
            factory,
            user_id=user_id,
            offer=offer,
            transaction_ref="txn_unknown",
        )
        body = _event(
            event_id="evt_unknown_price",
            event_type="transaction.completed",
            occurred_at=now,
            user_id=user_id,
            offer_key=offer.key,
            data={
                "id": "txn_unknown",
                "customer_id": "ctm_buyer",
                "status": "completed",
                "items": [{"price": {"id": "pri_not_ours"}}],
            },
        )
        with pytest.raises(PaddleWebhookError, match="price does not match"):
            await _deliver(gateway, body, now=now)

        stale_signature = paddle_signature_for_test(
            body,
            secret=_WEBHOOK_SECRET,
            timestamp=int((now - timedelta(minutes=1)).timestamp()),
        )
        with pytest.raises(PaddleWebhookSignatureError, match="outside tolerance"):
            await gateway.process_webhook(
                raw_body=body,
                signature_header=stale_signature,
                now=now,
            )
        with pytest.raises(PaddleWebhookSignatureError, match="invalid"):
            await gateway.process_webhook(
                raw_body=body,
                signature_header=f"ts={int(now.timestamp())};h1={'0' * 64}",
                now=now,
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_checkout_uses_server_owned_user_and_catalog_price_metadata() -> None:
    offer = _offer_30d()
    engine, factory, user_id, _, gateway = await _fixture(offer)
    requests: list[dict] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append({"path": request.url.path, "body": body})
        if request.url.path == "/customers":
            return httpx.Response(201, json={"data": {"id": "ctm_created"}})
        if request.url.path == "/transactions":
            return httpx.Response(
                201,
                json={
                    "data": {
                        "id": "txn_checkout",
                        "checkout": {"url": "https://pay.paddle.test/checkout"},
                    }
                },
            )
        return httpx.Response(404)

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://sandbox-api.paddle.com",
    )
    try:
        checkout = await gateway.create_checkout(
            user_id=user_id,
            email="buyer@example.com",
            offer_key="pro_30d",
            client=client,
        )
        assert checkout.checkout_url == "https://pay.paddle.test/checkout"
        assert [item["path"] for item in requests] == ["/customers", "/transactions"]
        transaction = requests[-1]["body"]
        assert transaction["items"] == [{"price_id": _PRICE_30D, "quantity": 1}]
        assert transaction["custom_data"] == {
            "dota_ai_billing": "dota-ai-billing-v1",
            "dota_user_id": str(user_id),
            "dota_plan": "PRO",
            "dota_offer": "pro_30d",
        }
        async with factory() as session:
            stored = await session.scalar(select(BillingCheckoutRecord))
            assert stored is not None
            assert stored.user_id == user_id
            assert stored.checkout_ref == "txn_checkout"
            assert stored.price_ref == _PRICE_30D
            assert stored.status == "PENDING"
    finally:
        await client.aclose()
        await engine.dispose()


@pytest.mark.asyncio
async def test_active_paddle_purchase_blocks_a_second_checkout_before_provider_api_call() -> None:
    offer = _offer_30d()
    engine, factory, user_id, now, gateway = await _fixture(offer)
    api_called = False

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal api_called
        api_called = True
        return httpx.Response(500)

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://sandbox-api.paddle.com",
    )
    try:
        async with factory.begin() as session:
            session.add(
                BillingSubscriptionRecord(
                    user_id=user_id,
                    provider="paddle",
                    subscription_ref="txn_existing",
                    customer_ref="ctm_existing",
                    plan_key="PRO",
                    access_state="ACTIVE",
                    provider_status="completed",
                    current_period_end=now + timedelta(days=10),
                    last_event_occurred_at=now,
                    created_at=now,
                    updated_at=now,
                )
            )
        with pytest.raises(PaddleCheckoutConflict, match="already exists"):
            await gateway.create_checkout(
                user_id=user_id,
                email="buyer@example.com",
                offer_key="pro_30d",
                client=client,
            )
        assert api_called is False
    finally:
        await client.aclose()
        await engine.dispose()
