from __future__ import annotations

import hmac
import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote
from uuid import UUID

import httpx
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.billing.models import BillingCheckoutRecord, BillingSubscriptionRecord
from app.billing.service import (
    BILLING_ACCESS_ACTIVE,
    BILLING_ACCESS_INACTIVE,
    PRO_PLAN,
    BillingEntitlementService,
    BillingEventResult,
)

PADDLE_PROVIDER = "paddle"
_PADDLE_SCHEMA_MARKER = "dota-ai-billing-v1"
_ACTIVE_SUBSCRIPTION_STATUSES = frozenset({"active", "trialing"})
_INACTIVE_SUBSCRIPTION_STATUSES = frozenset({"past_due", "paused", "canceled"})
_SUBSCRIPTION_EVENTS = frozenset(
    {
        "subscription.created",
        "subscription.activated",
        "subscription.trialing",
        "subscription.resumed",
        "subscription.updated",
        "subscription.past_due",
        "subscription.paused",
        "subscription.canceled",
    }
)
_ADJUSTMENT_EVENTS = frozenset({"adjustment.created", "adjustment.updated"})


class PaddleApiError(RuntimeError):
    pass


class PaddleCheckoutConflict(ValueError):
    pass


class PaddleWebhookError(ValueError):
    pass


class PaddleWebhookSignatureError(PaddleWebhookError):
    pass


@dataclass(frozen=True, slots=True)
class PaddleOffer:
    key: str
    label: str
    price_id: str
    recurring: bool
    grant_days: int | None
    supports_alipay: bool
    supports_wechat_pay: bool

    def public_payload(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "kind": "subscription" if self.recurring else "fixed_term",
            "grant_days": self.grant_days,
            "entitlements": ["ai_decisions", "realtime_notifications"],
            "payment_methods": {
                "card": "subscription" if self.recurring else "one_time",
                "alipay": (
                    "subscription"
                    if self.recurring and self.supports_alipay
                    else "one_time"
                    if self.supports_alipay
                    else "unavailable"
                ),
                "wechat_pay": (
                    "one_time"
                    if self.supports_wechat_pay and not self.recurring
                    else "not_supported_for_subscription"
                    if self.recurring
                    else "unavailable"
                ),
            },
        }


@dataclass(frozen=True, slots=True)
class PaddleCatalogPrice:
    price_id: str
    amount: str
    currency_code: str
    status: str
    recurring: bool

    def public_payload(self) -> dict[str, str]:
        return {
            "id": self.price_id,
            "amount": self.amount,
            "currency_code": self.currency_code,
        }


@dataclass(frozen=True, slots=True)
class PaddleCheckout:
    transaction_ref: str
    customer_ref: str
    checkout_url: str


@dataclass(frozen=True, slots=True)
class PaddleWebhookResult:
    event_ref: str
    event_type: str
    ignored: bool
    duplicate: bool = False
    stale: bool = False
    active_entitlements: tuple[str, ...] = ()


class PaddleApiClient:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        timeout_seconds: float = 15.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=httpx.Timeout(timeout_seconds),
        )
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Paddle-Version": "1",
        }

    async def create_customer(self, *, email: str, user_id: UUID) -> str:
        payload = await self._request(
            "POST",
            "/customers",
            json_body={
                "email": email,
                "custom_data": {
                    "dota_ai_billing": _PADDLE_SCHEMA_MARKER,
                    "dota_user_id": str(user_id),
                },
            },
        )
        data = _response_data(payload)
        customer_ref = data.get("id")
        if not isinstance(customer_ref, str) or not customer_ref.startswith("ctm_"):
            raise PaddleApiError("Paddle customer response is missing a valid customer id")
        return customer_ref

    async def get_price(self, price_id: str) -> PaddleCatalogPrice:
        payload = await self._request("GET", f"/prices/{quote(price_id, safe='')}")
        data = _response_data(payload)
        response_price_id = data.get("id")
        unit_price = data.get("unit_price")
        amount = unit_price.get("amount") if isinstance(unit_price, dict) else None
        currency_code = (
            unit_price.get("currency_code") if isinstance(unit_price, dict) else None
        )
        status = data.get("status")
        if response_price_id != price_id:
            raise PaddleApiError("Paddle price response does not match the requested price")
        if not isinstance(amount, str) or not amount.isdigit():
            raise PaddleApiError("Paddle price response is missing a valid amount")
        if not isinstance(currency_code, str) or len(currency_code) != 3:
            raise PaddleApiError("Paddle price response is missing a valid currency")
        if not isinstance(status, str):
            raise PaddleApiError("Paddle price response is missing a valid status")
        return PaddleCatalogPrice(
            price_id=response_price_id,
            amount=amount,
            currency_code=currency_code.upper(),
            status=status.lower(),
            recurring=data.get("billing_cycle") is not None,
        )

    async def create_checkout(
        self,
        *,
        user_id: UUID,
        customer_ref: str,
        offer: PaddleOffer,
        checkout_url: str | None,
    ) -> PaddleCheckout:
        body: dict[str, Any] = {
            "items": [{"price_id": offer.price_id, "quantity": 1}],
            "customer_id": customer_ref,
            "collection_mode": "automatic",
            "custom_data": {
                "dota_ai_billing": _PADDLE_SCHEMA_MARKER,
                "dota_user_id": str(user_id),
                "dota_plan": PRO_PLAN,
                "dota_offer": offer.key,
            },
        }
        if checkout_url:
            body["checkout"] = {"url": checkout_url}
        payload = await self._request("POST", "/transactions", json_body=body)
        data = _response_data(payload)
        transaction_ref = data.get("id")
        checkout = data.get("checkout")
        payment_link = checkout.get("url") if isinstance(checkout, dict) else None
        if not isinstance(transaction_ref, str) or not transaction_ref.startswith("txn_"):
            raise PaddleApiError("Paddle transaction response is missing a valid transaction id")
        if not isinstance(payment_link, str) or not payment_link.startswith(
            ("https://", "http://")
        ):
            raise PaddleApiError(
                "Paddle did not return a checkout URL; configure a default payment link "
                "or approved checkout URL"
            )
        return PaddleCheckout(transaction_ref, customer_ref, payment_link)

    async def create_portal_session(
        self,
        *,
        customer_ref: str,
        subscription_refs: tuple[str, ...] = (),
    ) -> str:
        body: dict[str, Any] = {}
        if subscription_refs:
            body["subscription_ids"] = list(subscription_refs[:25])
        payload = await self._request(
            "POST",
            f"/customers/{customer_ref}/portal-sessions",
            json_body=body,
        )
        data = _response_data(payload)
        urls = data.get("urls")
        general = urls.get("general") if isinstance(urls, dict) else None
        overview = general.get("overview") if isinstance(general, dict) else None
        if not isinstance(overview, str) or not overview.startswith("https://"):
            raise PaddleApiError("Paddle portal session response is missing an overview URL")
        return overview

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            response = await self._client.request(
                method,
                path,
                json=json_body,
                headers=self._headers,
            )
        except httpx.HTTPError as exc:
            raise PaddleApiError(f"Paddle API request failed: {type(exc).__name__}") from exc
        if response.status_code < 200 or response.status_code >= 300:
            request_id = response.headers.get("request-id") or response.headers.get("x-request-id")
            suffix = f" request_id={request_id}" if request_id else ""
            raise PaddleApiError(f"Paddle API returned HTTP {response.status_code}.{suffix}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise PaddleApiError("Paddle API returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise PaddleApiError("Paddle API returned a non-object response")
        return payload


class PaddleBillingGateway:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        api_key: str,
        webhook_secret: str,
        api_base_url: str,
        offers: tuple[PaddleOffer, ...],
        checkout_url: str | None = None,
        api_timeout_seconds: float = 15.0,
        webhook_tolerance_seconds: int = 5,
    ) -> None:
        if not offers:
            raise ValueError("at least one Paddle billing offer is required")
        self._session_factory = session_factory
        self._billing = BillingEntitlementService(session_factory)
        self._api_key = api_key
        self._webhook_secret = webhook_secret
        self._api_base_url = api_base_url.rstrip("/")
        self._checkout_url = checkout_url.strip() if checkout_url and checkout_url.strip() else None
        self._api_timeout_seconds = api_timeout_seconds
        self._webhook_tolerance_seconds = webhook_tolerance_seconds
        self._offers = {offer.key: offer for offer in offers}
        self._offers_by_price = {offer.price_id: offer for offer in offers}
        if len(self._offers_by_price) != len(self._offers):
            raise ValueError("Paddle billing price ids must be unique")

    @property
    def offers(self) -> tuple[PaddleOffer, ...]:
        return tuple(self._offers.values())

    async def create_checkout(
        self,
        *,
        user_id: UUID,
        email: str,
        offer_key: str,
        client: httpx.AsyncClient | None = None,
    ) -> PaddleCheckout:
        offer = self._offers.get(offer_key)
        if offer is None:
            raise ValueError(f"unknown Paddle billing offer: {offer_key}")
        if await self._has_active_paddle_purchase(user_id):
            raise PaddleCheckoutConflict(
                "an active Paddle Pro purchase already exists; use the customer portal"
            )
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
            checkout = await api.create_checkout(
                user_id=user_id,
                customer_ref=customer_ref,
                offer=offer,
                checkout_url=self._checkout_url,
            )
            await self._record_checkout(user_id=user_id, offer=offer, checkout=checkout)
            return checkout
        finally:
            await api.close()

    async def create_portal_url(
        self,
        *,
        user_id: UUID,
        client: httpx.AsyncClient | None = None,
    ) -> str | None:
        customer_ref = await self._known_customer_ref(user_id)
        if customer_ref is None:
            return None
        subscription_refs = await self._subscription_refs(user_id)
        api = PaddleApiClient(
            api_key=self._api_key,
            base_url=self._api_base_url,
            timeout_seconds=self._api_timeout_seconds,
            client=client,
        )
        try:
            return await api.create_portal_session(
                customer_ref=customer_ref,
                subscription_refs=subscription_refs,
            )
        finally:
            await api.close()

    async def process_webhook(
        self,
        *,
        raw_body: bytes,
        signature_header: str | None,
        now: datetime | None = None,
    ) -> PaddleWebhookResult:
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
        occurred_at = _parse_datetime(payload.get("occurred_at"), "event occurrence time")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise PaddleWebhookError("Paddle webhook data must be an object")

        if event_type == "transaction.completed":
            result = await self._apply_completed_transaction(
                event_ref=event_ref,
                event_type=event_type,
                occurred_at=occurred_at,
                data=data,
            )
        elif event_type in _SUBSCRIPTION_EVENTS:
            result = await self._apply_subscription(
                event_ref=event_ref,
                event_type=event_type,
                occurred_at=occurred_at,
                data=data,
            )
        elif event_type in _ADJUSTMENT_EVENTS:
            result = await self._apply_adjustment(
                event_ref=event_ref,
                event_type=event_type,
                occurred_at=occurred_at,
                data=data,
            )
        else:
            return PaddleWebhookResult(event_ref, event_type, ignored=True)

        if result is None:
            return PaddleWebhookResult(event_ref, event_type, ignored=True)
        return PaddleWebhookResult(
            event_ref,
            event_type,
            ignored=False,
            duplicate=result.duplicate,
            stale=result.stale,
            active_entitlements=result.active_entitlements,
        )

    async def _apply_completed_transaction(
        self,
        *,
        event_ref: str,
        event_type: str,
        occurred_at: datetime,
        data: dict[str, Any],
    ) -> BillingEventResult | None:
        transaction_ref = _required_string(data.get("id"), "transaction id")
        checkout = await self._checkout_record(transaction_ref)
        if checkout is None:
            # A signed Paddle event is not enough to establish application
            # account ownership. Only a checkout created by our authenticated
            # server is allowed to provision access.
            return None
        offer = self._validated_checkout_offer(checkout, data)
        customer_ref = _optional_string(data.get("customer_id"))
        if customer_ref is not None and checkout.customer_ref not in {None, customer_ref}:
            raise PaddleWebhookError("Paddle transaction customer does not match server checkout")
        provider_status = _optional_string(data.get("status")) or event_type
        subscription_ref = _optional_string(data.get("subscription_id"))
        if offer.recurring:
            if subscription_ref is None:
                raise PaddleWebhookError("recurring Paddle transaction is missing subscription_id")
            current_period_end = _period_end(data) or occurred_at + timedelta(days=32)
        else:
            if offer.grant_days is None or offer.grant_days < 1:
                raise PaddleWebhookError("fixed-term Paddle offer is missing grant duration")
            subscription_ref = transaction_ref
            current_period_end = occurred_at + timedelta(days=offer.grant_days)
        result = await self._billing.apply_subscription_event(
            provider=PADDLE_PROVIDER,
            event_ref=event_ref,
            occurred_at=occurred_at,
            user_id=checkout.user_id,
            subscription_ref=subscription_ref,
            customer_ref=customer_ref or checkout.customer_ref,
            plan_key=checkout.plan_key,
            access_state=BILLING_ACCESS_ACTIVE,
            provider_status=provider_status,
            current_period_end=current_period_end,
        )
        await self._mark_checkout_completed(checkout.checkout_ref, occurred_at)
        return result

    async def _apply_subscription(
        self,
        *,
        event_ref: str,
        event_type: str,
        occurred_at: datetime,
        data: dict[str, Any],
    ) -> BillingEventResult | None:
        subscription_ref = _required_string(data.get("id"), "subscription id")
        record = await self._billing_record(subscription_ref)
        payment_blocked = record is not None and _is_payment_blocked(record.provider_status)
        checkout: BillingCheckoutRecord | None = None
        if record is None and event_type == "subscription.created":
            transaction_ref = _optional_string(data.get("transaction_id"))
            checkout = await self._checkout_record(transaction_ref) if transaction_ref else None
            if checkout is None:
                return None
            offer = self._validated_checkout_offer(checkout, data)
            if not offer.recurring:
                raise PaddleWebhookError(
                    "fixed-term Paddle checkout unexpectedly created a subscription"
                )
            user_id = checkout.user_id
            plan_key = checkout.plan_key
            customer_ref = _optional_string(data.get("customer_id")) or checkout.customer_ref
        elif record is not None:
            offer = self._offer_from_data(data)
            if offer is None or not offer.recurring:
                raise PaddleWebhookError(
                    "mapped Paddle subscription contains an unknown recurring price"
                )
            user_id = record.user_id
            plan_key = record.plan_key
            customer_ref = _optional_string(data.get("customer_id")) or record.customer_ref
        else:
            return None

        status = (_optional_string(data.get("status")) or "").lower()
        if event_type in {
            "subscription.activated",
            "subscription.resumed",
            "subscription.trialing",
        }:
            access_state = BILLING_ACCESS_ACTIVE
        elif event_type in {
            "subscription.past_due",
            "subscription.paused",
            "subscription.canceled",
        }:
            access_state = BILLING_ACCESS_INACTIVE
        elif status in _ACTIVE_SUBSCRIPTION_STATUSES:
            access_state = BILLING_ACCESS_ACTIVE
        elif status in _INACTIVE_SUBSCRIPTION_STATUSES:
            access_state = BILLING_ACCESS_INACTIVE
        else:
            raise PaddleWebhookError(
                f"unsupported Paddle subscription status: {status or 'missing'}"
            )
        provider_status = status or event_type
        if payment_blocked and record is not None:
            access_state = BILLING_ACCESS_INACTIVE
            provider_status = record.provider_status
        period_end = _period_end(data)
        if access_state == BILLING_ACCESS_ACTIVE and period_end is None:
            period_end = occurred_at + timedelta(days=32)
        result = await self._billing.apply_subscription_event(
            provider=PADDLE_PROVIDER,
            event_ref=event_ref,
            occurred_at=occurred_at,
            user_id=user_id,
            subscription_ref=subscription_ref,
            customer_ref=customer_ref,
            plan_key=plan_key,
            access_state=access_state,
            provider_status=provider_status,
            current_period_end=period_end,
        )
        if checkout is not None:
            await self._mark_checkout_completed(checkout.checkout_ref, occurred_at)
        return result

    async def _apply_adjustment(
        self,
        *,
        event_ref: str,
        event_type: str,
        occurred_at: datetime,
        data: dict[str, Any],
    ) -> BillingEventResult | None:
        status = (_optional_string(data.get("status")) or "").lower()
        if status != "approved":
            return None
        adjustment_type = (_optional_string(data.get("type")) or "").lower()
        if adjustment_type != "full":
            return None
        action = (_optional_string(data.get("action")) or "").lower()
        if action not in {"refund", "chargeback", "chargeback_warning"}:
            # Reversals are deliberately not treated as proof that a recurring
            # subscription is safe to reactivate. Keep the billing source blocked
            # until a new purchase or an explicit operator reconciliation.
            return None
        subscription_ref = _optional_string(data.get("subscription_id")) or _optional_string(
            data.get("transaction_id")
        )
        if subscription_ref is None:
            raise PaddleWebhookError("approved Paddle adjustment is missing a billing reference")
        record = await self._billing_record(subscription_ref)
        if record is None:
            return None
        return await self._billing.apply_subscription_event(
            provider=PADDLE_PROVIDER,
            event_ref=event_ref,
            occurred_at=occurred_at,
            user_id=record.user_id,
            subscription_ref=record.subscription_ref,
            customer_ref=_optional_string(data.get("customer_id")) or record.customer_ref,
            plan_key=record.plan_key,
            access_state=BILLING_ACCESS_INACTIVE,
            provider_status=f"blocked:{action}:approved",
            current_period_end=record.current_period_end,
        )

    def _validated_checkout_offer(
        self,
        checkout: BillingCheckoutRecord,
        data: dict[str, Any],
    ) -> PaddleOffer:
        offer = self._offers.get(checkout.offer_key)
        if (
            offer is None
            or offer.price_id != checkout.price_ref
            or offer.recurring != checkout.recurring
            or offer.grant_days != checkout.grant_days
            or checkout.plan_key != PRO_PLAN
        ):
            raise PaddleWebhookError("server checkout references an unsupported Paddle offer")
        webhook_offer = self._offer_from_data(data)
        if webhook_offer is None or webhook_offer.key != offer.key:
            raise PaddleWebhookError("Paddle event price does not match server checkout")
        custom = data.get("custom_data")
        if not isinstance(custom, dict):
            raise PaddleWebhookError("Paddle event is missing server checkout metadata")
        if (
            custom.get("dota_ai_billing") != _PADDLE_SCHEMA_MARKER
            or custom.get("dota_user_id") != str(checkout.user_id)
            or custom.get("dota_offer") != checkout.offer_key
            or custom.get("dota_plan") != checkout.plan_key
        ):
            raise PaddleWebhookError("Paddle event metadata does not match server checkout")
        return offer

    def _offer_from_data(self, data: dict[str, Any]) -> PaddleOffer | None:
        items = data.get("items")
        if not isinstance(items, list):
            return None
        matched: list[PaddleOffer] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            price_ref = _optional_string(item.get("price_id"))
            price = item.get("price")
            if price_ref is None and isinstance(price, dict):
                price_ref = _optional_string(price.get("id"))
            if price_ref is not None and price_ref in self._offers_by_price:
                matched.append(self._offers_by_price[price_ref])
        unique = {offer.key: offer for offer in matched}
        if not unique:
            return None
        if len(unique) != 1:
            raise PaddleWebhookError("Paddle billing event contains multiple configured Pro offers")
        return next(iter(unique.values()))

    async def _record_checkout(
        self,
        *,
        user_id: UUID,
        offer: PaddleOffer,
        checkout: PaddleCheckout,
    ) -> None:
        now = datetime.now(UTC)
        async with self._session_factory() as session, session.begin():
            existing = await session.scalar(
                select(BillingCheckoutRecord)
                .where(
                    BillingCheckoutRecord.provider == PADDLE_PROVIDER,
                    BillingCheckoutRecord.checkout_ref == checkout.transaction_ref,
                )
                .limit(1)
                .with_for_update()
            )
            if existing is not None:
                if (
                    existing.user_id != user_id
                    or existing.offer_key != offer.key
                    or existing.price_ref != offer.price_id
                ):
                    raise PaddleApiError("Paddle transaction id collided with another checkout")
                return
            session.add(
                BillingCheckoutRecord(
                    user_id=user_id,
                    provider=PADDLE_PROVIDER,
                    checkout_ref=checkout.transaction_ref,
                    customer_ref=checkout.customer_ref,
                    offer_key=offer.key,
                    price_ref=offer.price_id,
                    plan_key=PRO_PLAN,
                    recurring=offer.recurring,
                    grant_days=offer.grant_days,
                    status="PENDING",
                    created_at=now,
                    updated_at=now,
                )
            )

    async def _mark_checkout_completed(self, checkout_ref: str, occurred_at: datetime) -> None:
        async with self._session_factory() as session, session.begin():
            record = await session.scalar(
                select(BillingCheckoutRecord)
                .where(
                    BillingCheckoutRecord.provider == PADDLE_PROVIDER,
                    BillingCheckoutRecord.checkout_ref == checkout_ref,
                )
                .limit(1)
                .with_for_update()
            )
            if record is not None:
                record.status = "COMPLETED"
                record.completed_at = occurred_at
                record.updated_at = datetime.now(UTC)

    async def _checkout_record(self, checkout_ref: str | None) -> BillingCheckoutRecord | None:
        if checkout_ref is None:
            return None
        async with self._session_factory() as session:
            return await session.scalar(
                select(BillingCheckoutRecord)
                .where(
                    BillingCheckoutRecord.provider == PADDLE_PROVIDER,
                    BillingCheckoutRecord.checkout_ref == checkout_ref,
                )
                .limit(1)
            )

    async def _has_active_paddle_purchase(self, user_id: UUID) -> bool:
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            row = await session.scalar(
                select(BillingSubscriptionRecord.id)
                .where(
                    BillingSubscriptionRecord.user_id == user_id,
                    BillingSubscriptionRecord.provider == PADDLE_PROVIDER,
                    BillingSubscriptionRecord.access_state == BILLING_ACCESS_ACTIVE,
                    or_(
                        BillingSubscriptionRecord.current_period_end.is_(None),
                        BillingSubscriptionRecord.current_period_end > now,
                    ),
                )
                .limit(1)
            )
        return row is not None

    async def _known_customer_ref(self, user_id: UUID) -> str | None:
        async with self._session_factory() as session:
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

    async def _subscription_refs(self, user_id: UUID) -> tuple[str, ...]:
        async with self._session_factory() as session:
            refs = list(
                (
                    await session.scalars(
                        select(BillingSubscriptionRecord.subscription_ref)
                        .where(
                            BillingSubscriptionRecord.user_id == user_id,
                            BillingSubscriptionRecord.provider == PADDLE_PROVIDER,
                            BillingSubscriptionRecord.subscription_ref.like("sub_%"),
                        )
                        .order_by(BillingSubscriptionRecord.updated_at.desc())
                    )
                ).all()
            )
        return tuple(dict.fromkeys(refs))

    async def _billing_record(self, subscription_ref: str) -> BillingSubscriptionRecord | None:
        async with self._session_factory() as session:
            return await session.scalar(
                select(BillingSubscriptionRecord)
                .where(
                    BillingSubscriptionRecord.provider == PADDLE_PROVIDER,
                    BillingSubscriptionRecord.subscription_ref == subscription_ref,
                )
                .limit(1)
            )


def verify_paddle_signature(
    raw_body: bytes,
    signature_header: str | None,
    *,
    secret: str,
    now: datetime | None = None,
    tolerance_seconds: int = 5,
) -> None:
    if not signature_header:
        raise PaddleWebhookSignatureError("Paddle-Signature header is required")
    if tolerance_seconds < 1:
        raise ValueError("Paddle webhook tolerance must be positive")
    parts: dict[str, list[str]] = {}
    for segment in signature_header.split(";"):
        key, separator, value = segment.partition("=")
        if not separator or not key or not value:
            raise PaddleWebhookSignatureError("Paddle-Signature header is malformed")
        parts.setdefault(key.strip(), []).append(value.strip())
    timestamps = parts.get("ts", [])
    signatures = parts.get("h1", [])
    if len(timestamps) != 1 or not signatures:
        raise PaddleWebhookSignatureError("Paddle-Signature header is missing ts or h1")
    try:
        timestamp = int(timestamps[0])
    except ValueError as exc:
        raise PaddleWebhookSignatureError("Paddle-Signature timestamp is invalid") from exc
    current = int((now or datetime.now(UTC)).timestamp())
    if abs(current - timestamp) > tolerance_seconds:
        raise PaddleWebhookSignatureError("Paddle webhook signature timestamp is outside tolerance")
    signed_payload = str(timestamp).encode("ascii") + b":" + raw_body
    expected = hmac.new(secret.encode("utf-8"), signed_payload, "sha256").hexdigest()
    if not any(hmac.compare_digest(expected, candidate) for candidate in signatures):
        raise PaddleWebhookSignatureError("Paddle webhook signature is invalid")


def paddle_signature_for_test(raw_body: bytes, *, secret: str, timestamp: int | None = None) -> str:
    value = timestamp if timestamp is not None else int(time.time())
    signed_payload = str(value).encode("ascii") + b":" + raw_body
    digest = hmac.new(secret.encode("utf-8"), signed_payload, "sha256").hexdigest()
    return f"ts={value};h1={digest}"


def _is_payment_blocked(provider_status: str | None) -> bool:
    return bool(provider_status and provider_status.startswith("blocked:"))


def _period_end(data: dict[str, Any]) -> datetime | None:
    for key in ("current_billing_period", "billing_period"):
        period = data.get(key)
        if not isinstance(period, dict):
            continue
        value = period.get("ends_at")
        if value is not None:
            return _parse_datetime(value, f"{key}.ends_at")
    return None


def _parse_datetime(value: object, label: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise PaddleWebhookError(f"Paddle {label} is required")
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise PaddleWebhookError(f"Paddle {label} is invalid") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _required_string(value: object, label: str) -> str:
    result = _optional_string(value)
    if result is None:
        raise PaddleWebhookError(f"Paddle {label} is required")
    return result


def _optional_string(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _response_data(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data")
    if not isinstance(data, dict):
        raise PaddleApiError("Paddle API response is missing data")
    return data
