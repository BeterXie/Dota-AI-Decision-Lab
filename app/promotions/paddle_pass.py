from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.models import UserAccountRecord
from app.billing.models import BillingCheckoutRecord, BillingSubscriptionRecord
from app.billing.paddle import (
    PADDLE_PROVIDER,
    PaddleApiClient,
    PaddleCheckout,
    PaddleOffer,
    PaddleWebhookError,
    verify_paddle_signature,
)
from app.entitlements import (
    ACCESS_SCOPE_EVENT,
    ACCESS_SCOPE_SERIES,
    AI_DECISIONS_ENTITLEMENT,
    PREMIUM_ENTITLEMENTS,
    EntitlementService,
    UserEntitlementRecord,
)
from app.models import CanonicalEvent, CanonicalSeries
from app.promotions.models import CompetitionPassEventRecord, CompetitionPassPurchaseRecord

PassScope = Literal["EVENT", "SERIES"]


class CompetitionPassCheckoutConflict(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class CompetitionPassWebhookResult:
    event_ref: str
    event_type: str
    ignored: bool
    duplicate: bool = False
    stale: bool = False
    activated: bool = False
    revoked: bool = False


@dataclass(frozen=True, slots=True)
class _PassTarget:
    scope_type: PassScope
    scope_ref: UUID
    canonical_series_id: UUID | None
    canonical_event_id: UUID | None


class PaddleCompetitionPassService:
    """Paddle adapter for a permanent pass bound to an event or BO series."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        scope_type: PassScope,
        api_key: str,
        webhook_secret: str,
        api_base_url: str,
        price_id: str,
        checkout_url: str | None = None,
        api_timeout_seconds: float = 15.0,
        webhook_tolerance_seconds: int = 5,
    ) -> None:
        if scope_type not in {ACCESS_SCOPE_EVENT, ACCESS_SCOPE_SERIES}:
            raise ValueError("competition pass scope must be EVENT or SERIES")
        if not price_id.strip():
            raise ValueError("competition pass Paddle price id is required")
        self._session_factory = session_factory
        self._entitlements = EntitlementService(session_factory)
        self._scope_type = scope_type
        self._api_key = api_key
        self._webhook_secret = webhook_secret
        self._api_base_url = api_base_url.rstrip("/")
        self._price_id = price_id.strip()
        self._checkout_url = checkout_url.strip() if checkout_url and checkout_url.strip() else None
        self._api_timeout_seconds = api_timeout_seconds
        self._webhook_tolerance_seconds = webhook_tolerance_seconds
        self._offer = PaddleOffer(
            key=f"{scope_type.lower()}_pass",
            label=f"{scope_type.title()} Pass",
            price_id=self._price_id,
            recurring=False,
            grant_days=None,
            supports_alipay=True,
            supports_wechat_pay=True,
        )

    @property
    def public_offer(self) -> dict:
        return {
            "enabled": True,
            "key": self._offer.key,
            "label": self._offer.label,
            "kind": "one_time_scope",
            "scope_type": self._scope_type,
            "non_expiring": True,
            "entitlements": list(PREMIUM_ENTITLEMENTS),
            "payment_methods": {
                "card": "one_time",
                "alipay": "one_time",
                "wechat_pay": "one_time",
            },
        }

    async def create_checkout(
        self,
        *,
        user_id: UUID,
        email: str,
        target_id: UUID,
        client: httpx.AsyncClient | None = None,
    ) -> PaddleCheckout:
        target = await self._target(target_id)
        existing_scope = await self._entitlements.access_scope(
            user_id,
            AI_DECISIONS_ENTITLEMENT,
            canonical_event_id=target.canonical_event_id,
            canonical_series_id=target.canonical_series_id,
        )
        if existing_scope is not None:
            raise CompetitionPassCheckoutConflict(
                "this account already has AI access to the selected competition scope"
            )

        intent_id = await self._reserve_purchase_intent(user_id, target)
        customer_ref = await self._known_customer_ref(user_id)
        api = PaddleApiClient(
            api_key=self._api_key,
            base_url=self._api_base_url,
            timeout_seconds=self._api_timeout_seconds,
            client=client,
        )
        try:
            if customer_ref is None:
                customer_ref = await api.create_customer(email=email, user_id=user_id)
                await self._remember_intent_customer(intent_id, customer_ref)
            checkout = await api.create_checkout(
                user_id=user_id,
                customer_ref=customer_ref,
                offer=self._offer,
                checkout_url=self._checkout_url,
            )
            await self._finalize_purchase_intent(intent_id=intent_id, checkout=checkout)
            return checkout
        except Exception:
            await self._mark_intent_failed(intent_id)
            raise
        finally:
            await api.close()

    async def process_webhook(
        self,
        *,
        raw_body: bytes,
        signature_header: str | None,
        now: datetime | None = None,
    ) -> CompetitionPassWebhookResult:
        verify_paddle_signature(
            raw_body,
            signature_header,
            secret=self._webhook_secret,
            now=now,
            tolerance_seconds=self._webhook_tolerance_seconds,
        )
        try:
            payload = json.loads(raw_body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PaddleWebhookError("Paddle webhook body is not valid JSON") from exc
        if not isinstance(payload, dict):
            raise PaddleWebhookError("Paddle webhook body must be a JSON object")
        event_ref = _required_string(payload.get("event_id"), "event id")
        event_type = _required_string(payload.get("event_type"), "event type")
        occurred_at = _parse_datetime(payload.get("occurred_at"))
        data = payload.get("data")
        if not isinstance(data, dict):
            raise PaddleWebhookError("Paddle webhook data must be an object")

        if event_type == "transaction.completed":
            transaction_ref = _required_string(data.get("id"), "transaction id")
            mode = "ACTIVATE"
        elif event_type in {"adjustment.created", "adjustment.updated"}:
            if str(data.get("status") or "").lower() != "approved":
                return CompetitionPassWebhookResult(event_ref, event_type, ignored=True)
            if str(data.get("type") or "").lower() != "full":
                return CompetitionPassWebhookResult(event_ref, event_type, ignored=True)
            if str(data.get("action") or "").lower() not in {
                "refund",
                "chargeback",
                "chargeback_warning",
            }:
                return CompetitionPassWebhookResult(event_ref, event_type, ignored=True)
            transaction_ref = _optional_string(data.get("transaction_id"))
            if transaction_ref is None:
                return CompetitionPassWebhookResult(event_ref, event_type, ignored=True)
            mode = "REVOKE"
        else:
            return CompetitionPassWebhookResult(event_ref, event_type, ignored=True)

        return await self._apply_event(
            event_ref=event_ref,
            event_type=event_type,
            occurred_at=occurred_at,
            transaction_ref=transaction_ref,
            mode=mode,
            data=data,
            payload_digest=hashlib.blake2s(raw_body, digest_size=16).hexdigest(),
        )

    async def _target(self, target_id: UUID) -> _PassTarget:
        async with self._session_factory() as session:
            if self._scope_type == ACCESS_SCOPE_EVENT:
                event = await session.get(CanonicalEvent, target_id)
                if event is None:
                    raise ValueError("canonical event does not exist")
                return _PassTarget(ACCESS_SCOPE_EVENT, event.id, None, event.id)
            series = await session.get(CanonicalSeries, target_id)
            if series is None:
                raise ValueError("canonical series does not exist")
            return _PassTarget(ACCESS_SCOPE_SERIES, series.id, series.id, None)

    async def _apply_event(
        self,
        *,
        event_ref: str,
        event_type: str,
        occurred_at: datetime,
        transaction_ref: str,
        mode: str,
        data: dict,
        payload_digest: str,
    ) -> CompetitionPassWebhookResult:
        async with self._session_factory() as session, session.begin():
            purchase = await session.scalar(
                select(CompetitionPassPurchaseRecord)
                .where(
                    CompetitionPassPurchaseRecord.provider == PADDLE_PROVIDER,
                    CompetitionPassPurchaseRecord.transaction_ref == transaction_ref,
                    CompetitionPassPurchaseRecord.scope_type == self._scope_type,
                )
                .limit(1)
                .with_for_update()
            )
            if purchase is None:
                return CompetitionPassWebhookResult(event_ref, event_type, ignored=True)
            existing = await session.scalar(
                select(CompetitionPassEventRecord)
                .where(
                    CompetitionPassEventRecord.provider == PADDLE_PROVIDER,
                    CompetitionPassEventRecord.event_ref == event_ref,
                )
                .limit(1)
                .with_for_update()
            )
            if existing is not None:
                if existing.payload_digest != payload_digest:
                    raise PaddleWebhookError("Paddle event id was replayed with different content")
                return CompetitionPassWebhookResult(
                    event_ref,
                    event_type,
                    ignored=False,
                    duplicate=True,
                    stale=not existing.applied,
                )
            if (
                purchase.last_event_occurred_at is not None
                and occurred_at < _as_utc(purchase.last_event_occurred_at)
            ):
                session.add(
                    _event_record(
                        event_ref=event_ref,
                        transaction_ref=transaction_ref,
                        purchase=purchase,
                        occurred_at=occurred_at,
                        payload_digest=payload_digest,
                        applied=False,
                    )
                )
                return CompetitionPassWebhookResult(
                    event_ref, event_type, ignored=False, stale=True
                )

            activated = False
            revoked = False
            if mode == "ACTIVATE":
                _validate_completed_transaction(data, purchase, expected_price=self._price_id)
                if not purchase.payment_blocked:
                    purchase.status = "ACTIVE"
                    purchase.completed_at = occurred_at
                    await _upsert_pass_grants(
                        session,
                        purchase=purchase,
                        starts_at=occurred_at,
                        active=True,
                    )
                    activated = True
            else:
                purchase.status = "BLOCKED"
                purchase.payment_blocked = True
                await _upsert_pass_grants(
                    session,
                    purchase=purchase,
                    starts_at=purchase.completed_at or occurred_at,
                    active=False,
                )
                revoked = True

            purchase.last_event_occurred_at = occurred_at
            purchase.updated_at = datetime.now(UTC)
            session.add(
                _event_record(
                    event_ref=event_ref,
                    transaction_ref=transaction_ref,
                    purchase=purchase,
                    occurred_at=occurred_at,
                    payload_digest=payload_digest,
                    applied=True,
                )
            )
            return CompetitionPassWebhookResult(
                event_ref,
                event_type,
                ignored=False,
                activated=activated,
                revoked=revoked,
            )

    async def _reserve_purchase_intent(self, user_id: UUID, target: _PassTarget) -> UUID:
        threshold = datetime.now(UTC) - timedelta(hours=1)
        now = datetime.now(UTC)
        async with self._session_factory() as session, session.begin():
            account = await session.scalar(
                select(UserAccountRecord)
                .where(UserAccountRecord.id == user_id)
                .limit(1)
                .with_for_update()
            )
            if account is None or account.disabled_at is not None:
                raise CompetitionPassCheckoutConflict("active account required")
            predicates = [
                CompetitionPassPurchaseRecord.user_id == user_id,
                CompetitionPassPurchaseRecord.scope_type == target.scope_type,
                CompetitionPassPurchaseRecord.provider == PADDLE_PROVIDER,
                CompetitionPassPurchaseRecord.status == "PENDING",
                CompetitionPassPurchaseRecord.created_at > threshold,
            ]
            if target.scope_type == ACCESS_SCOPE_EVENT:
                predicates.append(
                    CompetitionPassPurchaseRecord.canonical_event_id == target.scope_ref
                )
            else:
                predicates.append(
                    CompetitionPassPurchaseRecord.canonical_series_id == target.scope_ref
                )
            pending = await session.scalar(
                select(CompetitionPassPurchaseRecord.id).where(*predicates).limit(1)
            )
            if pending is not None:
                raise CompetitionPassCheckoutConflict(
                    "a recent checkout for this competition scope is still pending"
                )
            intent = CompetitionPassPurchaseRecord(
                user_id=user_id,
                provider=PADDLE_PROVIDER,
                transaction_ref=f"intent:{uuid4().hex}",
                customer_ref=None,
                scope_type=target.scope_type,
                canonical_series_id=target.canonical_series_id,
                canonical_event_id=target.canonical_event_id,
                price_ref=self._price_id,
                status="PENDING",
                payment_blocked=False,
                created_at=now,
                updated_at=now,
            )
            session.add(intent)
            await session.flush()
            return intent.id

    async def _remember_intent_customer(self, intent_id: UUID, customer_ref: str) -> None:
        async with self._session_factory() as session, session.begin():
            intent = await session.get(
                CompetitionPassPurchaseRecord,
                intent_id,
                with_for_update=True,
            )
            if intent is not None and intent.status == "PENDING":
                intent.customer_ref = customer_ref
                intent.updated_at = datetime.now(UTC)

    async def _finalize_purchase_intent(self, *, intent_id: UUID, checkout: PaddleCheckout) -> None:
        async with self._session_factory() as session, session.begin():
            intent = await session.get(
                CompetitionPassPurchaseRecord,
                intent_id,
                with_for_update=True,
            )
            if intent is None or intent.status != "PENDING":
                raise RuntimeError("competition pass checkout intent is no longer pending")
            collision = await session.scalar(
                select(CompetitionPassPurchaseRecord.id)
                .where(
                    CompetitionPassPurchaseRecord.provider == PADDLE_PROVIDER,
                    CompetitionPassPurchaseRecord.transaction_ref == checkout.transaction_ref,
                    CompetitionPassPurchaseRecord.id != intent.id,
                )
                .limit(1)
            )
            if collision is not None:
                raise RuntimeError("Paddle transaction id collided with another checkout")
            intent.transaction_ref = checkout.transaction_ref
            intent.customer_ref = checkout.customer_ref
            intent.updated_at = datetime.now(UTC)

    async def _mark_intent_failed(self, intent_id: UUID) -> None:
        async with self._session_factory() as session, session.begin():
            intent = await session.get(
                CompetitionPassPurchaseRecord,
                intent_id,
                with_for_update=True,
            )
            if intent is not None and intent.status == "PENDING":
                intent.status = "FAILED"
                intent.updated_at = datetime.now(UTC)

    async def _known_customer_ref(self, user_id: UUID) -> str | None:
        async with self._session_factory() as session:
            purchase_customer = await session.scalar(
                select(CompetitionPassPurchaseRecord.customer_ref)
                .where(
                    CompetitionPassPurchaseRecord.user_id == user_id,
                    CompetitionPassPurchaseRecord.provider == PADDLE_PROVIDER,
                    CompetitionPassPurchaseRecord.customer_ref.is_not(None),
                )
                .order_by(CompetitionPassPurchaseRecord.created_at.desc())
                .limit(1)
            )
            if purchase_customer is not None:
                return purchase_customer
            subscription_customer = await session.scalar(
                select(BillingSubscriptionRecord.customer_ref)
                .where(
                    BillingSubscriptionRecord.user_id == user_id,
                    BillingSubscriptionRecord.provider == PADDLE_PROVIDER,
                    BillingSubscriptionRecord.customer_ref.is_not(None),
                )
                .order_by(BillingSubscriptionRecord.updated_at.desc())
                .limit(1)
            )
            if subscription_customer is not None:
                return subscription_customer
            return await session.scalar(
                select(BillingCheckoutRecord.customer_ref)
                .where(
                    BillingCheckoutRecord.user_id == user_id,
                    BillingCheckoutRecord.provider == PADDLE_PROVIDER,
                    BillingCheckoutRecord.customer_ref.is_not(None),
                )
                .order_by(BillingCheckoutRecord.created_at.desc())
                .limit(1)
            )


def _validate_completed_transaction(
    data: dict,
    purchase: CompetitionPassPurchaseRecord,
    *,
    expected_price: str,
) -> None:
    customer_ref = _optional_string(data.get("customer_id"))
    if purchase.customer_ref is not None and customer_ref not in {None, purchase.customer_ref}:
        raise PaddleWebhookError("Paddle transaction customer does not match server purchase")
    if _price_ids(data) != {expected_price} or purchase.price_ref != expected_price:
        raise PaddleWebhookError("Paddle transaction price does not match server catalog")
    custom = data.get("custom_data")
    if not isinstance(custom, dict):
        raise PaddleWebhookError("Paddle transaction is missing checkout metadata")
    if (
        custom.get("dota_user_id") != str(purchase.user_id)
        or custom.get("dota_offer")
        != f"{purchase.scope_type.lower()}_pass"
    ):
        raise PaddleWebhookError("Paddle transaction metadata does not match server purchase")


def _price_ids(data: dict) -> set[str]:
    items = data.get("items")
    if not isinstance(items, list):
        return set()
    result: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        value = item.get("price_id")
        price = item.get("price")
        if not isinstance(value, str) and isinstance(price, dict):
            value = price.get("id")
        if isinstance(value, str) and value:
            result.add(value)
    return result


async def _upsert_pass_grants(
    session: AsyncSession,
    *,
    purchase: CompetitionPassPurchaseRecord,
    starts_at: datetime,
    active: bool,
) -> None:
    source = f"billing:paddle-pass:{purchase.transaction_ref}"
    now = datetime.now(UTC)
    for entitlement in PREMIUM_ENTITLEMENTS:
        row = await session.scalar(
            select(UserEntitlementRecord)
            .where(
                UserEntitlementRecord.user_id == purchase.user_id,
                UserEntitlementRecord.entitlement == entitlement,
                UserEntitlementRecord.source == source,
            )
            .limit(1)
            .with_for_update()
        )
        if row is None:
            if not active:
                continue
            session.add(
                UserEntitlementRecord(
                    user_id=purchase.user_id,
                    entitlement=entitlement,
                    status="ACTIVE",
                    source=source,
                    scope_type=purchase.scope_type,
                    scope_ref=(
                        purchase.canonical_event_id
                        if purchase.scope_type == ACCESS_SCOPE_EVENT
                        else purchase.canonical_series_id
                    ),
                    campaign_key=None,
                    starts_at=starts_at,
                    expires_at=None,
                    created_at=now,
                    updated_at=now,
                )
            )
            continue
        expected_ref = (
            purchase.canonical_event_id
            if purchase.scope_type == ACCESS_SCOPE_EVENT
            else purchase.canonical_series_id
        )
        if row.scope_type != purchase.scope_type or row.scope_ref != expected_ref:
            raise PaddleWebhookError("Paddle pass source collided with another access scope")
        row.status = "ACTIVE" if active else "REVOKED"
        if active:
            row.starts_at = starts_at
            row.expires_at = None
        row.updated_at = now


def _event_record(
    *,
    event_ref: str,
    transaction_ref: str,
    purchase: CompetitionPassPurchaseRecord,
    occurred_at: datetime,
    payload_digest: str,
    applied: bool,
) -> CompetitionPassEventRecord:
    return CompetitionPassEventRecord(
        provider=PADDLE_PROVIDER,
        event_ref=event_ref,
        transaction_ref=transaction_ref,
        user_id=purchase.user_id,
        scope_type=purchase.scope_type,
        canonical_series_id=purchase.canonical_series_id,
        canonical_event_id=purchase.canonical_event_id,
        occurred_at=occurred_at,
        payload_digest=payload_digest,
        applied=applied,
        processed_at=datetime.now(UTC),
    )


def _required_string(value: object, label: str) -> str:
    result = _optional_string(value)
    if result is None:
        raise PaddleWebhookError(f"Paddle {label} is required")
    return result


def _optional_string(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _parse_datetime(value: object) -> datetime:
    result = _optional_string(value)
    if result is None:
        raise PaddleWebhookError("Paddle event occurrence time is required")
    try:
        parsed = datetime.fromisoformat(result.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PaddleWebhookError("Paddle event occurrence time is invalid") from exc
    return _as_utc(parsed)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
