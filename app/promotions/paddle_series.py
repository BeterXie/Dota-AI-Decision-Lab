from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
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
    ACCESS_SCOPE_SERIES,
    AI_DECISIONS_ENTITLEMENT,
    PREMIUM_ENTITLEMENTS,
    EntitlementService,
    UserEntitlementRecord,
)
from app.models import CanonicalSeries
from app.promotions.models import SeriesPassEventRecord, SeriesPassPurchaseRecord


class SeriesPassCheckoutConflict(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class SeriesPassWebhookResult:
    event_ref: str
    event_type: str
    ignored: bool
    duplicate: bool = False
    stale: bool = False
    activated: bool = False
    revoked: bool = False


class PaddleSeriesPassService:
    """Paddle one-time purchase adapter for one canonical BO series."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        api_key: str,
        webhook_secret: str,
        api_base_url: str,
        price_id: str,
        access_days: int = 3,
        checkout_url: str | None = None,
        api_timeout_seconds: float = 15.0,
        webhook_tolerance_seconds: int = 5,
    ) -> None:
        if not price_id.strip():
            raise ValueError("series pass Paddle price id is required")
        if access_days < 1 or access_days > 14:
            raise ValueError("series pass access days must be between 1 and 14")
        self._session_factory = session_factory
        self._entitlements = EntitlementService(session_factory)
        self._api_key = api_key
        self._webhook_secret = webhook_secret
        self._api_base_url = api_base_url.rstrip("/")
        self._price_id = price_id.strip()
        self._access_days = access_days
        self._checkout_url = checkout_url.strip() if checkout_url and checkout_url.strip() else None
        self._api_timeout_seconds = api_timeout_seconds
        self._webhook_tolerance_seconds = webhook_tolerance_seconds
        self._offer = PaddleOffer(
            key="series_pass",
            label="Pro Series Pass",
            price_id=self._price_id,
            recurring=False,
            grant_days=access_days,
            supports_alipay=True,
            supports_wechat_pay=True,
        )

    @property
    def public_offer(self) -> dict:
        return {
            **self._offer.public_payload(),
            "scope_type": ACCESS_SCOPE_SERIES,
            "access_days": self._access_days,
        }

    async def create_checkout(
        self,
        *,
        user_id: UUID,
        email: str,
        canonical_series_id: UUID,
        client: httpx.AsyncClient | None = None,
    ) -> PaddleCheckout:
        async with self._session_factory() as session:
            series = await session.get(CanonicalSeries, canonical_series_id)
            if series is None:
                raise ValueError("canonical series does not exist")
        if await self._entitlements.has_resource_entitlement(
            user_id,
            AI_DECISIONS_ENTITLEMENT,
            canonical_series_id=canonical_series_id,
        ):
            raise SeriesPassCheckoutConflict("this account already has AI access to the series")

        # Reserve a durable intent before any external Paddle call. Reservation
        # locks the user row on PostgreSQL, so two app processes cannot both
        # create a paid transaction for the same account/series after racing the
        # pending check. The intent transaction_ref is replaced only after
        # Paddle returns the real txn_* identifier.
        intent_id = await self._reserve_purchase_intent(user_id, canonical_series_id)
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
            await self._finalize_purchase_intent(
                intent_id=intent_id,
                checkout=checkout,
            )
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
    ) -> SeriesPassWebhookResult:
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

        transaction_ref: str | None = None
        mode: str | None = None
        if event_type == "transaction.completed":
            transaction_ref = _required_string(data.get("id"), "transaction id")
            mode = "ACTIVATE"
        elif event_type in {"adjustment.created", "adjustment.updated"}:
            if str(data.get("status") or "").lower() != "approved":
                return SeriesPassWebhookResult(event_ref, event_type, ignored=True)
            if str(data.get("type") or "").lower() != "full":
                return SeriesPassWebhookResult(event_ref, event_type, ignored=True)
            action = str(data.get("action") or "").lower()
            if action not in {"refund", "chargeback", "chargeback_warning"}:
                # Reversals deliberately do not auto-regrant in V1.
                return SeriesPassWebhookResult(event_ref, event_type, ignored=True)
            value = data.get("transaction_id")
            transaction_ref = value.strip() if isinstance(value, str) and value.strip() else None
            if transaction_ref is None:
                return SeriesPassWebhookResult(event_ref, event_type, ignored=True)
            mode = "REVOKE"
        else:
            return SeriesPassWebhookResult(event_ref, event_type, ignored=True)

        return await self._apply_event(
            event_ref=event_ref,
            event_type=event_type,
            occurred_at=occurred_at,
            transaction_ref=transaction_ref,
            mode=mode,
            data=data,
            payload_digest=hashlib.sha256(raw_body).hexdigest(),
        )

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
    ) -> SeriesPassWebhookResult:
        async with self._session_factory() as session, session.begin():
            purchase = await session.scalar(
                select(SeriesPassPurchaseRecord)
                .where(
                    SeriesPassPurchaseRecord.provider == PADDLE_PROVIDER,
                    SeriesPassPurchaseRecord.transaction_ref == transaction_ref,
                )
                .limit(1)
                .with_for_update()
            )
            if purchase is None:
                return SeriesPassWebhookResult(event_ref, event_type, ignored=True)
            existing = await session.scalar(
                select(SeriesPassEventRecord)
                .where(
                    SeriesPassEventRecord.provider == PADDLE_PROVIDER,
                    SeriesPassEventRecord.event_ref == event_ref,
                )
                .limit(1)
                .with_for_update()
            )
            if existing is not None:
                if existing.payload_digest != payload_digest:
                    raise PaddleWebhookError(
                        "series pass event id was replayed with different content"
                    )
                return SeriesPassWebhookResult(
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
                return SeriesPassWebhookResult(
                    event_ref,
                    event_type,
                    ignored=False,
                    stale=True,
                )

            activated = False
            revoked = False
            if mode == "ACTIVATE":
                _validate_completed_transaction(data, purchase, expected_price=self._price_id)
                if not purchase.payment_blocked:
                    expires_at = occurred_at + timedelta(days=self._access_days)
                    purchase.status = "ACTIVE"
                    purchase.completed_at = occurred_at
                    purchase.grant_expires_at = expires_at
                    await _upsert_series_grants(
                        session,
                        purchase=purchase,
                        starts_at=occurred_at,
                        expires_at=expires_at,
                        active=True,
                    )
                    activated = True
            else:
                purchase.status = "BLOCKED"
                purchase.payment_blocked = True
                await _upsert_series_grants(
                    session,
                    purchase=purchase,
                    starts_at=purchase.completed_at or occurred_at,
                    expires_at=purchase.grant_expires_at,
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
            return SeriesPassWebhookResult(
                event_ref,
                event_type,
                ignored=False,
                activated=activated,
                revoked=revoked,
            )

    async def _reserve_purchase_intent(self, user_id: UUID, series_id: UUID) -> UUID:
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
                raise SeriesPassCheckoutConflict("active account required")
            pending = await session.scalar(
                select(SeriesPassPurchaseRecord.id)
                .where(
                    SeriesPassPurchaseRecord.user_id == user_id,
                    SeriesPassPurchaseRecord.canonical_series_id == series_id,
                    SeriesPassPurchaseRecord.provider == PADDLE_PROVIDER,
                    SeriesPassPurchaseRecord.status == "PENDING",
                    SeriesPassPurchaseRecord.created_at > threshold,
                )
                .limit(1)
            )
            if pending is not None:
                raise SeriesPassCheckoutConflict(
                    "a recent checkout for this series is still pending; complete or abandon it first"
                )
            intent = SeriesPassPurchaseRecord(
                user_id=user_id,
                provider=PADDLE_PROVIDER,
                transaction_ref=f"intent:{uuid4().hex}",
                customer_ref=None,
                canonical_series_id=series_id,
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
                SeriesPassPurchaseRecord,
                intent_id,
                with_for_update=True,
            )
            if intent is not None and intent.status == "PENDING":
                intent.customer_ref = customer_ref
                intent.updated_at = datetime.now(UTC)

    async def _finalize_purchase_intent(
        self,
        *,
        intent_id: UUID,
        checkout: PaddleCheckout,
    ) -> None:
        async with self._session_factory() as session, session.begin():
            intent = await session.get(
                SeriesPassPurchaseRecord,
                intent_id,
                with_for_update=True,
            )
            if intent is None or intent.status != "PENDING":
                raise RuntimeError("series pass checkout intent is no longer pending")
            collision = await session.scalar(
                select(SeriesPassPurchaseRecord.id)
                .where(
                    SeriesPassPurchaseRecord.provider == PADDLE_PROVIDER,
                    SeriesPassPurchaseRecord.transaction_ref == checkout.transaction_ref,
                    SeriesPassPurchaseRecord.id != intent.id,
                )
                .limit(1)
            )
            if collision is not None:
                raise RuntimeError("Paddle series transaction id collided with another checkout")
            intent.transaction_ref = checkout.transaction_ref
            intent.customer_ref = checkout.customer_ref
            intent.updated_at = datetime.now(UTC)

    async def _mark_intent_failed(self, intent_id: UUID) -> None:
        async with self._session_factory() as session, session.begin():
            intent = await session.get(
                SeriesPassPurchaseRecord,
                intent_id,
                with_for_update=True,
            )
            if intent is not None and intent.status == "PENDING":
                intent.status = "FAILED"
                intent.updated_at = datetime.now(UTC)

    async def _known_customer_ref(self, user_id: UUID) -> str | None:
        async with self._session_factory() as session:
            scoped_customer = await session.scalar(
                select(SeriesPassPurchaseRecord.customer_ref)
                .where(
                    SeriesPassPurchaseRecord.user_id == user_id,
                    SeriesPassPurchaseRecord.provider == PADDLE_PROVIDER,
                    SeriesPassPurchaseRecord.customer_ref.is_not(None),
                )
                .order_by(SeriesPassPurchaseRecord.created_at.desc())
                .limit(1)
            )
            if scoped_customer is not None:
                return scoped_customer
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
    purchase: SeriesPassPurchaseRecord,
    *,
    expected_price: str,
) -> None:
    customer_ref = data.get("customer_id")
    if (
        purchase.customer_ref is not None
        and isinstance(customer_ref, str)
        and customer_ref
        and customer_ref != purchase.customer_ref
    ):
        raise PaddleWebhookError("series pass customer does not match server purchase mapping")
    prices = _price_ids(data)
    if prices != {expected_price} or purchase.price_ref != expected_price:
        raise PaddleWebhookError("series pass price does not match server catalog")
    custom = data.get("custom_data")
    if not isinstance(custom, dict):
        raise PaddleWebhookError("series pass transaction is missing checkout metadata")
    if (
        custom.get("dota_user_id") != str(purchase.user_id)
        or custom.get("dota_offer") != "series_pass"
    ):
        raise PaddleWebhookError("series pass checkout metadata does not match server mapping")


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


async def _upsert_series_grants(
    session: AsyncSession,
    *,
    purchase: SeriesPassPurchaseRecord,
    starts_at: datetime,
    expires_at: datetime | None,
    active: bool,
) -> None:
    source = _series_source(purchase.transaction_ref)
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
                    scope_type=ACCESS_SCOPE_SERIES,
                    scope_ref=purchase.canonical_series_id,
                    campaign_key=None,
                    starts_at=starts_at,
                    expires_at=expires_at,
                    created_at=now,
                    updated_at=now,
                )
            )
            continue
        if (
            row.scope_type != ACCESS_SCOPE_SERIES
            or row.scope_ref != purchase.canonical_series_id
        ):
            raise PaddleWebhookError("series pass source collided with another access scope")
        row.status = "ACTIVE" if active else "REVOKED"
        if active:
            row.starts_at = starts_at
            row.expires_at = expires_at
        row.updated_at = now


def _event_record(
    *,
    event_ref: str,
    transaction_ref: str,
    purchase: SeriesPassPurchaseRecord,
    occurred_at: datetime,
    payload_digest: str,
    applied: bool,
) -> SeriesPassEventRecord:
    return SeriesPassEventRecord(
        provider=PADDLE_PROVIDER,
        event_ref=event_ref,
        transaction_ref=transaction_ref,
        user_id=purchase.user_id,
        canonical_series_id=purchase.canonical_series_id,
        occurred_at=occurred_at,
        payload_digest=payload_digest,
        applied=applied,
        processed_at=datetime.now(UTC),
    )


def _series_source(transaction_ref: str) -> str:
    digest = hashlib.sha256(transaction_ref.encode("utf-8")).hexdigest()[:24]
    return f"billing:paddle-series:{digest}"


def _required_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PaddleWebhookError(f"Paddle {label} is required")
    return value.strip()


def _parse_datetime(value: object) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise PaddleWebhookError("Paddle event occurrence time is required")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise PaddleWebhookError("Paddle event occurrence time is invalid") from exc
    return _as_utc(parsed)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
