import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.auth.models import UserAccountRecord
from app.db import Base
from app.entitlements import PREMIUM_ENTITLEMENTS, EntitlementService, UserEntitlementRecord
from app.models import CanonicalEvent
from app.promotions import PromotionService, ReferralClaimError
from app.promotions.models import CompetitionPassPurchaseRecord, ReferralAttributionRecord


async def _fixture():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime.now(UTC).replace(microsecond=0)
    async with factory.begin() as session:
        inviter = UserAccountRecord(
            email="inviter@example.com",
            email_verified_at=now,
            last_login_at=now,
            created_at=now,
        )
        invited = UserAccountRecord(
            email="invited@example.com",
            email_verified_at=now,
            last_login_at=now,
            created_at=now,
        )
        session.add_all([inviter, invited])
        await session.flush()
        inviter_id = inviter.id
        invited_id = invited.id
    service = PromotionService(
        factory,
        referral_enabled=True,
        campaign_key="launch-referral",
        claim_window_days=7,
        inviter_reward_days=7,
        invited_reward_days=3,
        max_rewards_per_inviter=20,
    )
    return engine, factory, service, inviter_id, invited_id, now


@pytest.mark.asyncio
async def test_referral_claim_requires_another_recent_account_and_is_idempotent() -> None:
    engine, _, service, inviter_id, invited_id, now = await _fixture()
    try:
        first_code, second_code = await asyncio.gather(
            service.ensure_referral_code(inviter_id),
            service.ensure_referral_code(inviter_id),
        )
        assert first_code == second_code
        attribution = await service.claim_referral(invited_id, first_code, now=now)
        duplicate = await service.claim_referral(invited_id, first_code, now=now)
        assert duplicate.id == attribution.id
        assert attribution.inviter_user_id == inviter_id
        assert attribution.status == "CLAIMED"

        with pytest.raises(ReferralClaimError, match="cannot refer itself"):
            await service.claim_referral(inviter_id, first_code, now=now)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_referral_cannot_be_claimed_after_first_paid_purchase() -> None:
    engine, factory, service, inviter_id, invited_id, now = await _fixture()
    try:
        code = await service.ensure_referral_code(inviter_id)
        async with factory.begin() as session:
            event = CanonicalEvent(name="Referral Event")
            session.add(event)
            await session.flush()
            session.add(
                CompetitionPassPurchaseRecord(
                    user_id=invited_id,
                    provider="paddle",
                    transaction_ref="txn_already_paid",
                    customer_ref="ctm_existing",
                    price_ref="pri_existing",
                    scope_type="EVENT",
                    canonical_event_id=event.id,
                    status="COMPLETED",
                    completed_at=now,
                    created_at=now,
                    updated_at=now,
                )
            )
        with pytest.raises(ReferralClaimError, match="before.*first paid purchase"):
            await service.claim_referral(invited_id, code, now=now)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_first_paid_purchase_grants_both_users_and_refund_revokes_reward_source() -> None:
    engine, factory, service, inviter_id, invited_id, now = await _fixture()
    entitlements = EntitlementService(factory)
    try:
        code = await service.ensure_referral_code(inviter_id)
        attribution = await service.claim_referral(invited_id, code, now=now)
        assert (
            await service.qualify_referral_payment(
                invited_id,
                provider="paddle",
                payment_ref="txn_first_paid",
                occurred_at=now + timedelta(minutes=1),
            )
            is True
        )
        assert set(
            await entitlements.active_entitlements(
                inviter_id,
                now=now + timedelta(days=1),
            )
        ) == set(PREMIUM_ENTITLEMENTS)
        assert set(
            await entitlements.active_entitlements(
                invited_id,
                now=now + timedelta(days=1),
            )
        ) == set(PREMIUM_ENTITLEMENTS)
        assert (
            await service.qualify_referral_payment(
                invited_id,
                provider="paddle",
                payment_ref="txn_second_paid",
                occurred_at=now + timedelta(minutes=2),
            )
            is False
        )

        assert (
            await service.revoke_referral_payment(
                provider="paddle",
                payment_ref="txn_first_paid",
                revoked_at=now + timedelta(hours=1),
            )
            is True
        )
        assert (
            await entitlements.active_entitlements(
                inviter_id,
                now=now + timedelta(hours=2),
            )
            == ()
        )
        assert (
            await entitlements.active_entitlements(
                invited_id,
                now=now + timedelta(hours=2),
            )
            == ()
        )
        async with factory() as session:
            stored = await session.get(ReferralAttributionRecord, attribution.id)
            assert stored is not None and stored.status == "REVOKED"
            reward_rows = list(
                (
                    await session.scalars(
                        select(UserEntitlementRecord).where(
                            UserEntitlementRecord.campaign_key == "launch-referral"
                        )
                    )
                ).all()
            )
            assert reward_rows
            assert {item.status for item in reward_rows} == {"REVOKED"}
    finally:
        await engine.dispose()
