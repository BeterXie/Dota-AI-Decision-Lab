import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.billing.models import BillingEventRecord, BillingSubscriptionRecord
from app.entitlements.models import UserEntitlementRecord
from app.entitlements.service import PREMIUM_ENTITLEMENTS

BILLING_ACCESS_ACTIVE = "ACTIVE"
BILLING_ACCESS_INACTIVE = "INACTIVE"
PRO_PLAN = "PRO"
_PLAN_ENTITLEMENTS = {PRO_PLAN: PREMIUM_ENTITLEMENTS}


class BillingEventConflict(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class BillingEventResult:
    duplicate: bool
    active_entitlements: tuple[str, ...]


class BillingEntitlementService:
    """Provider-neutral billing lifecycle mapped onto user entitlements.

    Provider adapters are responsible only for validating their webhook and
    mapping provider-specific subscription states to ACTIVE or INACTIVE. This
    service owns idempotency and entitlement mutation in one database transaction.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def apply_subscription_event(
        self,
        *,
        provider: str,
        event_ref: str,
        user_id: UUID,
        subscription_ref: str,
        plan_key: str,
        access_state: str,
        customer_ref: str | None = None,
        provider_status: str | None = None,
        current_period_end: datetime | None = None,
    ) -> BillingEventResult:
        normalized_provider = _required(provider, "billing provider").lower()
        normalized_event_ref = _required(event_ref, "billing event reference")
        normalized_subscription_ref = _required(subscription_ref, "billing subscription reference")
        normalized_plan = _required(plan_key, "billing plan").upper()
        normalized_state = _required(access_state, "billing access state").upper()
        if normalized_plan not in _PLAN_ENTITLEMENTS:
            raise ValueError(f"unsupported billing plan: {plan_key}")
        if normalized_state not in {BILLING_ACCESS_ACTIVE, BILLING_ACCESS_INACTIVE}:
            raise ValueError(f"unsupported billing access state: {access_state}")
        current_period_end = _as_utc(current_period_end)
        digest = _event_digest(
            user_id=user_id,
            subscription_ref=normalized_subscription_ref,
            plan_key=normalized_plan,
            access_state=normalized_state,
            customer_ref=customer_ref,
            provider_status=provider_status,
            current_period_end=current_period_end,
        )
        now = datetime.now(UTC)
        source = _billing_source(normalized_provider, normalized_subscription_ref)

        async with self._session_factory() as session, session.begin():
            existing_event = await session.scalar(
                select(BillingEventRecord)
                .where(
                    BillingEventRecord.provider == normalized_provider,
                    BillingEventRecord.event_ref == normalized_event_ref,
                )
                .limit(1)
                .with_for_update()
            )
            if existing_event is not None:
                if existing_event.payload_digest != digest:
                    raise BillingEventConflict(
                        "billing event reference was replayed with different normalized content"
                    )
                active = await _active_entitlements(session, user_id, now=now)
                return BillingEventResult(True, active)

            subscription = await session.scalar(
                select(BillingSubscriptionRecord)
                .where(
                    BillingSubscriptionRecord.provider == normalized_provider,
                    BillingSubscriptionRecord.subscription_ref == normalized_subscription_ref,
                )
                .limit(1)
                .with_for_update()
            )
            if subscription is None:
                subscription = BillingSubscriptionRecord(
                    user_id=user_id,
                    provider=normalized_provider,
                    subscription_ref=normalized_subscription_ref,
                    customer_ref=customer_ref,
                    plan_key=normalized_plan,
                    access_state=normalized_state,
                    provider_status=provider_status,
                    current_period_end=current_period_end,
                    created_at=now,
                    updated_at=now,
                )
                session.add(subscription)
            else:
                if subscription.user_id != user_id:
                    raise BillingEventConflict("billing subscription is already owned by another user")
                subscription.customer_ref = customer_ref or subscription.customer_ref
                subscription.plan_key = normalized_plan
                subscription.access_state = normalized_state
                subscription.provider_status = provider_status
                subscription.current_period_end = current_period_end
                subscription.updated_at = now

            plan_entitlements = _PLAN_ENTITLEMENTS[normalized_plan]
            for entitlement in PREMIUM_ENTITLEMENTS:
                row = await session.scalar(
                    select(UserEntitlementRecord)
                    .where(
                        UserEntitlementRecord.user_id == user_id,
                        UserEntitlementRecord.entitlement == entitlement,
                        UserEntitlementRecord.source == source,
                    )
                    .limit(1)
                    .with_for_update()
                )
                should_be_active = (
                    normalized_state == BILLING_ACCESS_ACTIVE and entitlement in plan_entitlements
                )
                if row is None:
                    if should_be_active:
                        session.add(
                            UserEntitlementRecord(
                                user_id=user_id,
                                entitlement=entitlement,
                                status="ACTIVE",
                                source=source,
                                starts_at=now,
                                expires_at=current_period_end,
                                created_at=now,
                                updated_at=now,
                            )
                        )
                    continue
                row.status = "ACTIVE" if should_be_active else "REVOKED"
                row.starts_at = now if should_be_active else row.starts_at
                row.expires_at = current_period_end if should_be_active else row.expires_at
                row.updated_at = now

            session.add(
                BillingEventRecord(
                    provider=normalized_provider,
                    event_ref=normalized_event_ref,
                    subscription_ref=normalized_subscription_ref,
                    user_id=user_id,
                    payload_digest=digest,
                    processed_at=now,
                )
            )
            await session.flush()
            active = await _active_entitlements(session, user_id, now=now)
            return BillingEventResult(False, active)


async def _active_entitlements(
    session: AsyncSession,
    user_id: UUID,
    *,
    now: datetime,
) -> tuple[str, ...]:
    rows = list(
        (
            await session.scalars(
                select(UserEntitlementRecord).where(
                    UserEntitlementRecord.user_id == user_id,
                    UserEntitlementRecord.status == "ACTIVE",
                )
            )
        ).all()
    )
    active = {
        row.entitlement
        for row in rows
        if (row.starts_at is None or _as_utc(row.starts_at) <= now)
        and (row.expires_at is None or _as_utc(row.expires_at) > now)
    }
    return tuple(sorted(active))


def _billing_source(provider: str, subscription_ref: str) -> str:
    ref_digest = hashlib.sha256(subscription_ref.encode("utf-8")).hexdigest()[:24]
    return f"billing:{provider}:{ref_digest}"


def _event_digest(
    *,
    user_id: UUID,
    subscription_ref: str,
    plan_key: str,
    access_state: str,
    customer_ref: str | None,
    provider_status: str | None,
    current_period_end: datetime | None,
) -> str:
    payload = {
        "user_id": str(user_id),
        "subscription_ref": subscription_ref,
        "plan_key": plan_key,
        "access_state": access_state,
        "customer_ref": customer_ref,
        "provider_status": provider_status,
        "current_period_end": current_period_end.isoformat() if current_period_end else None,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _required(value: str, label: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{label} is required")
    return normalized


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
