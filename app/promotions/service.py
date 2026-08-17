from __future__ import annotations

import asyncio
import base64
import json
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.models import UserAccountRecord
from app.billing.models import BillingCheckoutRecord
from app.entitlements import (
    ACCESS_SCOPE_GLOBAL,
    PREMIUM_ENTITLEMENTS,
    UserEntitlementRecord,
)
from app.promotions.models import (
    ReferralAttributionRecord,
    ReferralCodeRecord,
    SeriesPassPurchaseRecord,
)

REFERRAL_STATUS_CLAIMED = "CLAIMED"
REFERRAL_STATUS_REWARDED = "REWARDED"
REFERRAL_STATUS_REVOKED = "REVOKED"


class PromotionDisabledError(RuntimeError):
    pass


class ReferralClaimError(ValueError):
    pass


class PromotionService:
    """Referral attribution and reward grants on top of the access-grant ledger."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        referral_enabled: bool = False,
        campaign_key: str = "referral-v1",
        claim_window_days: int = 7,
        inviter_reward_days: int = 7,
        invited_reward_days: int = 3,
        max_rewards_per_inviter: int = 20,
    ) -> None:
        if claim_window_days < 1:
            raise ValueError("referral claim window must be positive")
        if inviter_reward_days < 0 or invited_reward_days < 0:
            raise ValueError("referral reward days cannot be negative")
        if max_rewards_per_inviter < 1:
            raise ValueError("referral reward cap must be positive")
        self._session_factory = session_factory
        self.enabled = referral_enabled
        self.campaign_key = campaign_key.strip() or "referral-v1"
        self.claim_window_days = claim_window_days
        self.inviter_reward_days = inviter_reward_days
        self.invited_reward_days = invited_reward_days
        self.max_rewards_per_inviter = max_rewards_per_inviter
        # Same-process calls need an in-memory serialization point because
        # SQLite ignores SELECT ... FOR UPDATE in unit tests. PostgreSQL's
        # account-row lock below remains the cross-worker serialization guard.
        self._referral_code_locks: dict[UUID, asyncio.Lock] = {}

    async def overview(self, user_id: UUID) -> dict:
        if not self.enabled:
            return {
                "enabled": False,
                "campaign_key": self.campaign_key,
                "code": None,
                "claimed_invites": 0,
                "rewarded_invites": 0,
                "reward": self._reward_payload(),
            }
        code = await self.ensure_referral_code(user_id)
        async with self._session_factory() as session:
            claimed = await session.scalar(
                select(func.count())
                .select_from(ReferralAttributionRecord)
                .where(
                    ReferralAttributionRecord.inviter_user_id == user_id,
                    ReferralAttributionRecord.campaign_key == self.campaign_key,
                )
            )
            rewarded = await session.scalar(
                select(func.count())
                .select_from(ReferralAttributionRecord)
                .where(
                    ReferralAttributionRecord.inviter_user_id == user_id,
                    ReferralAttributionRecord.campaign_key == self.campaign_key,
                    ReferralAttributionRecord.status == REFERRAL_STATUS_REWARDED,
                )
            )
        return {
            "enabled": True,
            "campaign_key": self.campaign_key,
            "code": code,
            "claimed_invites": int(claimed or 0),
            "rewarded_invites": int(rewarded or 0),
            "reward": self._reward_payload(),
        }

    async def ensure_referral_code(self, user_id: UUID) -> str:
        if not self.enabled:
            raise PromotionDisabledError("referral campaign is disabled")
        lock = self._referral_code_locks.setdefault(user_id, asyncio.Lock())
        async with lock:
            return await self._ensure_referral_code_locked(user_id)

    async def _ensure_referral_code_locked(self, user_id: UUID) -> str:
        async with self._session_factory() as session, session.begin():
            # PostgreSQL serializes first-code creation per account across
            # application workers. The in-process asyncio lock above covers
            # engines without row-level FOR UPDATE semantics.
            account = await session.scalar(
                select(UserAccountRecord)
                .where(UserAccountRecord.id == user_id)
                .limit(1)
                .with_for_update()
            )
            if account is None or account.disabled_at is not None:
                raise ReferralClaimError("active account required")
            existing = await session.scalar(
                select(ReferralCodeRecord)
                .where(ReferralCodeRecord.user_id == user_id)
                .limit(1)
                .with_for_update()
            )
            if existing is not None:
                if existing.status != "ACTIVE":
                    existing.status = "ACTIVE"
                    existing.updated_at = datetime.now(UTC)
                return existing.code
            for _ in range(5):
                code = _new_referral_code()
                collision = await session.scalar(
                    select(ReferralCodeRecord.id).where(ReferralCodeRecord.code == code).limit(1)
                )
                if collision is None:
                    session.add(
                        ReferralCodeRecord(
                            user_id=user_id,
                            code=code,
                            status="ACTIVE",
                        )
                    )
                    await session.flush()
                    return code
        raise RuntimeError("could not allocate a unique referral code")

    async def claim_referral(
        self,
        invited_user_id: UUID,
        code: str,
        *,
        now: datetime | None = None,
    ) -> ReferralAttributionRecord:
        if not self.enabled:
            raise PromotionDisabledError("referral campaign is disabled")
        normalized_code = code.strip().upper()
        if not normalized_code:
            raise ReferralClaimError("referral code is required")
        current = now or datetime.now(UTC)
        async with self._session_factory() as session, session.begin():
            invited = await session.scalar(
                select(UserAccountRecord)
                .where(UserAccountRecord.id == invited_user_id)
                .limit(1)
                .with_for_update()
            )
            if invited is None or invited.disabled_at is not None:
                raise ReferralClaimError("active invited account required")
            if _as_utc(invited.created_at) < current - timedelta(days=self.claim_window_days):
                raise ReferralClaimError("referral claim window has expired")
            if await _has_prior_paid_purchase(session, invited_user_id):
                raise ReferralClaimError(
                    "referral must be claimed before the invited account's first paid purchase"
                )

            existing = await session.scalar(
                select(ReferralAttributionRecord)
                .where(ReferralAttributionRecord.invited_user_id == invited_user_id)
                .limit(1)
                .with_for_update()
            )
            code_record = await session.scalar(
                select(ReferralCodeRecord)
                .where(
                    ReferralCodeRecord.code == normalized_code,
                    ReferralCodeRecord.status == "ACTIVE",
                )
                .limit(1)
                .with_for_update()
            )
            if code_record is None:
                raise ReferralClaimError("referral code is invalid")
            if code_record.user_id == invited_user_id:
                raise ReferralClaimError("an account cannot refer itself")
            inviter = await session.get(UserAccountRecord, code_record.user_id)
            if inviter is None or inviter.disabled_at is not None:
                raise ReferralClaimError("referral code owner is not active")
            if existing is not None:
                if existing.referral_code_id == code_record.id:
                    return existing
                raise ReferralClaimError("this account already claimed a referral")

            attribution = ReferralAttributionRecord(
                inviter_user_id=code_record.user_id,
                invited_user_id=invited_user_id,
                referral_code_id=code_record.id,
                campaign_key=self.campaign_key,
                status=REFERRAL_STATUS_CLAIMED,
                claimed_at=current,
                created_at=current,
                updated_at=current,
            )
            session.add(attribution)
            await session.flush()
            return attribution

    async def handle_paddle_payment_event(
        self,
        raw_body: bytes,
        *,
        now: datetime | None = None,
    ) -> bool:
        """Qualify or revoke referral rewards after a verified Paddle webhook.

        The caller must invoke this only after Paddle-Signature verification and
        provider-specific purchase processing have succeeded.
        """

        if not self.enabled:
            return False
        try:
            payload = json.loads(raw_body)
        except UnicodeDecodeError, json.JSONDecodeError:
            return False
        if not isinstance(payload, dict):
            return False
        event_type = payload.get("event_type")
        data = payload.get("data")
        if not isinstance(event_type, str) or not isinstance(data, dict):
            return False
        occurred_at = _parse_provider_time(payload.get("occurred_at")) or now or datetime.now(UTC)

        if event_type == "transaction.completed":
            transaction_ref = data.get("id")
            if not isinstance(transaction_ref, str) or not transaction_ref:
                return False
            user_id = await self._paid_user_for_transaction(transaction_ref)
            if user_id is None:
                return False
            return await self.qualify_referral_payment(
                user_id,
                provider="paddle",
                payment_ref=transaction_ref,
                occurred_at=occurred_at,
            )

        if event_type not in {"adjustment.created", "adjustment.updated"}:
            return False
        if str(data.get("status") or "").lower() != "approved":
            return False
        if str(data.get("type") or "").lower() != "full":
            return False
        if str(data.get("action") or "").lower() not in {
            "refund",
            "chargeback",
            "chargeback_warning",
        }:
            return False
        transaction_ref = data.get("transaction_id")
        if not isinstance(transaction_ref, str) or not transaction_ref:
            return False
        return await self.revoke_referral_payment(
            provider="paddle",
            payment_ref=transaction_ref,
            revoked_at=occurred_at,
        )

    async def qualify_referral_payment(
        self,
        invited_user_id: UUID,
        *,
        provider: str,
        payment_ref: str,
        occurred_at: datetime,
    ) -> bool:
        if not self.enabled:
            return False
        normalized_provider = provider.strip().lower()
        normalized_payment = payment_ref.strip()
        if not normalized_provider or not normalized_payment:
            raise ValueError("payment provider and reference are required")
        current = _as_utc(occurred_at)
        async with self._session_factory() as session, session.begin():
            attribution = await session.scalar(
                select(ReferralAttributionRecord)
                .where(ReferralAttributionRecord.invited_user_id == invited_user_id)
                .limit(1)
                .with_for_update()
            )
            if attribution is None or attribution.status != REFERRAL_STATUS_CLAIMED:
                return False

            # The inviter row is the serialization point for reward-cap and
            # stacking decisions. Two different invited users can complete
            # payment concurrently, but only one transaction at a time computes
            # the inviter's rewarded-count and next reward window.
            inviter = await session.scalar(
                select(UserAccountRecord)
                .where(UserAccountRecord.id == attribution.inviter_user_id)
                .limit(1)
                .with_for_update()
            )
            invited = await session.scalar(
                select(UserAccountRecord)
                .where(UserAccountRecord.id == attribution.invited_user_id)
                .limit(1)
                .with_for_update()
            )
            if (
                inviter is None
                or inviter.disabled_at is not None
                or invited is None
                or invited.disabled_at is not None
            ):
                return False
            rewarded_count = await session.scalar(
                select(func.count())
                .select_from(ReferralAttributionRecord)
                .where(
                    ReferralAttributionRecord.inviter_user_id == attribution.inviter_user_id,
                    ReferralAttributionRecord.campaign_key == self.campaign_key,
                    ReferralAttributionRecord.status == REFERRAL_STATUS_REWARDED,
                )
            )
            if int(rewarded_count or 0) >= self.max_rewards_per_inviter:
                return False

            attribution.status = REFERRAL_STATUS_REWARDED
            attribution.qualified_provider = normalized_provider
            attribution.qualified_payment_ref = normalized_payment
            attribution.qualified_at = current
            attribution.rewarded_at = current
            attribution.updated_at = datetime.now(UTC)

            if self.inviter_reward_days > 0:
                await _grant_stacked_reward(
                    session,
                    user_id=attribution.inviter_user_id,
                    source=_reward_source(attribution.id, "inviter"),
                    campaign_key=self.campaign_key,
                    reward_days=self.inviter_reward_days,
                    now=current,
                )
            if self.invited_reward_days > 0:
                await _grant_stacked_reward(
                    session,
                    user_id=attribution.invited_user_id,
                    source=_reward_source(attribution.id, "invited"),
                    campaign_key=self.campaign_key,
                    reward_days=self.invited_reward_days,
                    now=current,
                )
            return True

    async def revoke_referral_payment(
        self,
        *,
        provider: str,
        payment_ref: str,
        revoked_at: datetime,
    ) -> bool:
        if not self.enabled:
            return False
        async with self._session_factory() as session, session.begin():
            attribution = await session.scalar(
                select(ReferralAttributionRecord)
                .where(
                    ReferralAttributionRecord.qualified_provider == provider.strip().lower(),
                    ReferralAttributionRecord.qualified_payment_ref == payment_ref.strip(),
                )
                .limit(1)
                .with_for_update()
            )
            if attribution is None or attribution.status != REFERRAL_STATUS_REWARDED:
                return False
            attribution.status = REFERRAL_STATUS_REVOKED
            attribution.revoked_at = _as_utc(revoked_at)
            attribution.updated_at = datetime.now(UTC)
            for user_id, role in (
                (attribution.inviter_user_id, "inviter"),
                (attribution.invited_user_id, "invited"),
            ):
                source = _reward_source(attribution.id, role)
                rows = list(
                    (
                        await session.scalars(
                            select(UserEntitlementRecord)
                            .where(
                                UserEntitlementRecord.user_id == user_id,
                                UserEntitlementRecord.source == source,
                                UserEntitlementRecord.status == "ACTIVE",
                            )
                            .with_for_update()
                        )
                    ).all()
                )
                for row in rows:
                    row.status = "REVOKED"
                    row.updated_at = datetime.now(UTC)
            return True

    async def _paid_user_for_transaction(self, transaction_ref: str) -> UUID | None:
        async with self._session_factory() as session:
            global_user = await session.scalar(
                select(BillingCheckoutRecord.user_id)
                .where(
                    BillingCheckoutRecord.provider == "paddle",
                    BillingCheckoutRecord.checkout_ref == transaction_ref,
                    BillingCheckoutRecord.status == "COMPLETED",
                )
                .limit(1)
            )
            if global_user is not None:
                return global_user
            return await session.scalar(
                select(SeriesPassPurchaseRecord.user_id)
                .where(
                    SeriesPassPurchaseRecord.provider == "paddle",
                    SeriesPassPurchaseRecord.transaction_ref == transaction_ref,
                    SeriesPassPurchaseRecord.status == "ACTIVE",
                    SeriesPassPurchaseRecord.payment_blocked.is_(False),
                )
                .limit(1)
            )

    def _reward_payload(self) -> dict:
        return {
            "trigger": "invited_user_first_paid_purchase",
            "inviter_days": self.inviter_reward_days,
            "invited_days": self.invited_reward_days,
            "max_rewards_per_inviter": self.max_rewards_per_inviter,
            "claim_window_days": self.claim_window_days,
        }


async def _has_prior_paid_purchase(session: AsyncSession, user_id: UUID) -> bool:
    global_purchase = await session.scalar(
        select(BillingCheckoutRecord.id)
        .where(
            BillingCheckoutRecord.user_id == user_id,
            BillingCheckoutRecord.provider == "paddle",
            BillingCheckoutRecord.status == "COMPLETED",
        )
        .limit(1)
    )
    if global_purchase is not None:
        return True
    series_purchase = await session.scalar(
        select(SeriesPassPurchaseRecord.id)
        .where(
            SeriesPassPurchaseRecord.user_id == user_id,
            SeriesPassPurchaseRecord.provider == "paddle",
            or_(
                SeriesPassPurchaseRecord.completed_at.is_not(None),
                SeriesPassPurchaseRecord.status.in_({"ACTIVE", "BLOCKED"}),
            ),
        )
        .limit(1)
    )
    return series_purchase is not None


async def _grant_stacked_reward(
    session: AsyncSession,
    *,
    user_id: UUID,
    source: str,
    campaign_key: str,
    reward_days: int,
    now: datetime,
) -> None:
    existing_end = await session.scalar(
        select(func.max(UserEntitlementRecord.expires_at)).where(
            UserEntitlementRecord.user_id == user_id,
            UserEntitlementRecord.campaign_key == campaign_key,
            UserEntitlementRecord.scope_type == ACCESS_SCOPE_GLOBAL,
            UserEntitlementRecord.status == "ACTIVE",
            UserEntitlementRecord.expires_at.is_not(None),
            UserEntitlementRecord.expires_at > now,
        )
    )
    starts_at = max(now, _as_utc(existing_end)) if existing_end is not None else now
    expires_at = starts_at + timedelta(days=reward_days)
    timestamp = datetime.now(UTC)
    for entitlement in PREMIUM_ENTITLEMENTS:
        session.add(
            UserEntitlementRecord(
                user_id=user_id,
                entitlement=entitlement,
                status="ACTIVE",
                source=source,
                scope_type=ACCESS_SCOPE_GLOBAL,
                scope_ref=None,
                campaign_key=campaign_key,
                starts_at=starts_at,
                expires_at=expires_at,
                created_at=timestamp,
                updated_at=timestamp,
            )
        )


def _new_referral_code() -> str:
    raw = base64.b32encode(secrets.token_bytes(8)).decode("ascii").rstrip("=")
    return raw[:12]


def _reward_source(attribution_id: UUID, role: str) -> str:
    return f"promo:referral:{attribution_id.hex}:{role}"


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _parse_provider_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return _as_utc(parsed)
