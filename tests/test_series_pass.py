import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.auth.models import UserAccountRecord
from app.billing.paddle import paddle_signature_for_test
from app.db import Base
from app.entitlements import (
    AI_DECISIONS_ENTITLEMENT,
    REALTIME_NOTIFICATIONS_ENTITLEMENT,
    EntitlementService,
)
from app.models import CanonicalEvent, CanonicalSeries, CanonicalTeam
from app.promotions.models import CompetitionPassPurchaseRecord
from app.promotions.paddle_event import PaddleEventPassService
from app.promotions.paddle_series import PaddleSeriesPassService

_SECRET = "pdl_pass_test_webhook_secret_long_enough"
_SERIES_PRICE = "pri_series_pass"
_EVENT_PRICE = "pri_event_pass"


async def _fixture():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime.now(UTC).replace(microsecond=0)
    async with factory.begin() as session:
        event = CanonicalEvent(name="Test Event")
        other_event = CanonicalEvent(name="Other Event")
        team_a = CanonicalTeam(name="Alpha")
        team_b = CanonicalTeam(name="Beta")
        team_c = CanonicalTeam(name="Gamma")
        session.add_all([event, other_event, team_a, team_b, team_c])
        await session.flush()
        series = CanonicalSeries(
            event_id=event.id,
            team_a_id=team_a.id,
            team_b_id=team_b.id,
            stage_key="PAID_STAGE",
            best_of=3,
            scheduled_at=now,
        )
        other_series = CanonicalSeries(
            event_id=event.id,
            team_a_id=team_a.id,
            team_b_id=team_c.id,
            stage_key="PAID_STAGE",
            best_of=3,
            scheduled_at=now,
        )
        foreign_series = CanonicalSeries(
            event_id=other_event.id,
            team_a_id=team_a.id,
            team_b_id=team_c.id,
            stage_key="PAID_STAGE",
            best_of=3,
            scheduled_at=now,
        )
        user = UserAccountRecord(
            email="pass@example.com",
            email_verified_at=now,
            last_login_at=now,
            created_at=now,
        )
        session.add_all([series, other_series, foreign_series, user])
        await session.flush()
        ids = (event.id, other_event.id, series.id, other_series.id, foreign_series.id, user.id)
        session.add(
            CompetitionPassPurchaseRecord(
                user_id=user.id,
                provider="paddle",
                transaction_ref="txn_series",
                customer_ref="ctm_pass",
                scope_type="SERIES",
                canonical_series_id=series.id,
                price_ref=_SERIES_PRICE,
                status="PENDING",
                payment_blocked=False,
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            CompetitionPassPurchaseRecord(
                user_id=user.id,
                provider="paddle",
                transaction_ref="txn_event",
                customer_ref="ctm_pass",
                scope_type="EVENT",
                canonical_event_id=event.id,
                price_ref=_EVENT_PRICE,
                status="PENDING",
                payment_blocked=False,
                created_at=now,
                updated_at=now,
            )
        )
    series_service = PaddleSeriesPassService(
        factory,
        api_key="pdl_sdbx_test",
        webhook_secret=_SECRET,
        api_base_url="https://sandbox-api.paddle.com",
        price_id=_SERIES_PRICE,
        webhook_tolerance_seconds=5,
    )
    event_service = PaddleEventPassService(
        factory,
        api_key="pdl_sdbx_test",
        webhook_secret=_SECRET,
        api_base_url="https://sandbox-api.paddle.com",
        price_id=_EVENT_PRICE,
        webhook_tolerance_seconds=5,
    )
    return engine, factory, series_service, event_service, ids, now


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


async def _deliver(service, body: bytes, *, now: datetime):
    return await service.process_webhook(
        raw_body=body,
        signature_header=paddle_signature_for_test(
            body,
            secret=_SECRET,
            timestamp=int(now.timestamp()),
        ),
        now=now,
    )


def _transaction(*, transaction_ref: str, price: str, user_id, offer: str) -> dict:
    return {
        "id": transaction_ref,
        "customer_id": "ctm_pass",
        "status": "completed",
        "items": [{"price": {"id": price}}],
        "custom_data": {
            "dota_user_id": str(user_id),
            "dota_offer": offer,
        },
    }


@pytest.mark.asyncio
async def test_series_pass_is_permanent_and_only_covers_one_series() -> None:
    engine, factory, series_service, _, ids, now = await _fixture()
    _, _, series_id, other_series_id, _, user_id = ids
    entitlements = EntitlementService(factory)
    try:
        body = _body(
            event_id="evt_series_paid",
            event_type="transaction.completed",
            occurred_at=now,
            data=_transaction(
                transaction_ref="txn_series",
                price=_SERIES_PRICE,
                user_id=user_id,
                offer="series_pass",
            ),
        )
        result = await _deliver(series_service, body, now=now)
        duplicate = await _deliver(series_service, body, now=now)
        assert result.activated is True
        assert duplicate.duplicate is True
        for entitlement in (AI_DECISIONS_ENTITLEMENT, REALTIME_NOTIFICATIONS_ENTITLEMENT):
            assert await entitlements.has_resource_entitlement(
                user_id,
                entitlement,
                canonical_series_id=series_id,
                now=now + timedelta(days=365),
            )
            assert not await entitlements.has_resource_entitlement(
                user_id,
                entitlement,
                canonical_series_id=other_series_id,
                now=now + timedelta(days=365),
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_event_pass_covers_all_series_in_event_and_refund_revokes() -> None:
    engine, factory, _, event_service, ids, now = await _fixture()
    event_id, _, series_id, other_series_id, foreign_series_id, user_id = ids
    entitlements = EntitlementService(factory)
    try:
        purchase = _body(
            event_id="evt_event_paid",
            event_type="transaction.completed",
            occurred_at=now,
            data=_transaction(
                transaction_ref="txn_event",
                price=_EVENT_PRICE,
                user_id=user_id,
                offer="event_pass",
            ),
        )
        result = await _deliver(event_service, purchase, now=now)
        assert result.activated is True
        assert (
            await entitlements.access_scope(
                user_id,
                AI_DECISIONS_ENTITLEMENT,
                canonical_event_id=event_id,
                canonical_series_id=series_id,
                now=now + timedelta(days=365),
            )
            == "EVENT"
        )
        assert await entitlements.has_resource_entitlement(
            user_id,
            AI_DECISIONS_ENTITLEMENT,
            canonical_series_id=other_series_id,
            now=now + timedelta(days=365),
        )
        assert not await entitlements.has_resource_entitlement(
            user_id,
            AI_DECISIONS_ENTITLEMENT,
            canonical_series_id=foreign_series_id,
            now=now + timedelta(days=365),
        )

        refund_at = now + timedelta(hours=1)
        refund = _body(
            event_id="evt_event_refund",
            event_type="adjustment.updated",
            occurred_at=refund_at,
            data={
                "id": "adj_event",
                "action": "refund",
                "type": "full",
                "status": "approved",
                "transaction_id": "txn_event",
            },
        )
        revoked = await _deliver(event_service, refund, now=refund_at)
        assert revoked.revoked is True
        assert not await entitlements.has_resource_entitlement(
            user_id,
            AI_DECISIONS_ENTITLEMENT,
            canonical_series_id=other_series_id,
            now=refund_at,
        )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_pass_checkout_binds_the_selected_series_before_payment() -> None:
    engine, factory, service, _, ids, _ = await _fixture()
    _, _, series_id, _, _, user_id = ids
    requests: list[dict] = []

    async def handler(request):
        requests.append(json.loads(request.content))
        if request.url.path == "/transactions":
            return httpx.Response(
                201,
                json={"data": {"id": "txn_new", "checkout": {"url": "https://pay.test"}}},
            )
        return httpx.Response(404)

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://sandbox-api.paddle.com",
    )
    try:
        async with factory.begin() as session:
            pending = await session.scalar(
                select(CompetitionPassPurchaseRecord).where(
                    CompetitionPassPurchaseRecord.transaction_ref == "txn_series"
                )
            )
            assert pending is not None
            pending.status = "FAILED"
        checkout = await service.create_checkout(
            user_id=user_id,
            email="pass@example.com",
            canonical_series_id=series_id,
            client=client,
        )
        assert checkout.transaction_ref == "txn_new"
        assert requests[-1]["items"] == [{"price_id": _SERIES_PRICE, "quantity": 1}]
        async with factory() as session:
            purchase = await session.scalar(
                select(CompetitionPassPurchaseRecord).where(
                    CompetitionPassPurchaseRecord.transaction_ref == "txn_new"
                )
            )
            assert purchase is not None
            assert purchase.scope_type == "SERIES"
            assert purchase.canonical_series_id == series_id
    finally:
        await client.aclose()
        await engine.dispose()
