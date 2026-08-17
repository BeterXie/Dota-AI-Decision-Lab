from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth import AuthenticatedUser
from app.billing.models import BillingSubscriptionRecord
from app.billing.paddle import (
    PADDLE_PROVIDER,
    PaddleApiError,
    PaddleBillingGateway,
    PaddleCheckoutConflict,
    PaddleOffer,
    PaddleWebhookError,
    PaddleWebhookSignatureError,
)
from app.config import Settings
from app.entitlements import EntitlementService
from app.promotions import PromotionService, SeriesPassCheckoutConflict
from app.promotions.config import PromotionSettings
from app.promotions.models import SeriesPassPurchaseRecord
from app.promotions.paddle_series import PaddleSeriesPassService

_MAX_PADDLE_WEBHOOK_BYTES = 1_048_576


def create_billing_router(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    *,
    promotion_settings: PromotionSettings | None = None,
    promotion_service: PromotionService | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/billing", tags=["billing"])
    promotions = promotion_settings or PromotionSettings()
    referral_service = promotion_service or _promotion_service(session_factory, promotions)
    offers = _configured_offers(settings)
    gateway = _gateway(settings, session_factory, offers)
    series_gateway = _series_gateway(settings, promotions, session_factory)
    entitlements = EntitlementService(session_factory)

    @router.get("/offers")
    async def billing_offers() -> dict[str, Any]:
        return {
            "provider": PADDLE_PROVIDER,
            "enabled": gateway is not None,
            "environment": settings.paddle_environment,
            "offers": [offer.public_payload() for offer in offers],
            "series_pass": (
                {
                    "enabled": True,
                    **series_gateway.public_offer,
                }
                if series_gateway is not None
                else {"enabled": False}
            ),
            "referral": {
                "enabled": referral_service.enabled,
                "campaign_key": referral_service.campaign_key,
            },
            "local_payment_notes": {
                "alipay": (
                    "Available for eligible China checkouts; recurring support depends on "
                    "Paddle approval and catalog currency."
                ),
                "wechat_pay": (
                    "Available for eligible China one-time purchases; recurring subscriptions "
                    "are not supported."
                ),
            },
            "crypto": {
                "enabled": False,
                "architecture": "separate_provider_adapter",
                "status": "disabled_by_default",
            },
        }

    @router.get("/account")
    async def billing_account(request: Request) -> dict[str, Any]:
        user = _request_user(request)
        async with session_factory() as session:
            records = list(
                (
                    await session.scalars(
                        select(BillingSubscriptionRecord)
                        .where(BillingSubscriptionRecord.user_id == user.id)
                        .order_by(BillingSubscriptionRecord.updated_at.desc())
                    )
                ).all()
            )
            series_passes = list(
                (
                    await session.scalars(
                        select(SeriesPassPurchaseRecord)
                        .where(SeriesPassPurchaseRecord.user_id == user.id)
                        .order_by(SeriesPassPurchaseRecord.created_at.desc())
                        .limit(50)
                    )
                ).all()
            )
        return {
            "entitlements": list(await entitlements.active_entitlements(user.id)),
            "grants": [item.public_payload() for item in await entitlements.active_grants(user.id)],
            "subscriptions": [
                {
                    "provider": item.provider,
                    "plan": item.plan_key,
                    "access_state": item.access_state,
                    "provider_status": item.provider_status,
                    "current_period_end": item.current_period_end,
                    "updated_at": item.updated_at,
                    "recurring": item.subscription_ref.startswith("sub_"),
                }
                for item in records
            ],
            "series_passes": [
                {
                    "provider": item.provider,
                    "canonical_series_id": str(item.canonical_series_id),
                    "status": item.status,
                    "grant_expires_at": item.grant_expires_at,
                    "completed_at": item.completed_at,
                    "payment_blocked": item.payment_blocked,
                }
                for item in series_passes
            ],
        }

    @router.post("/checkout/{offer_key}")
    async def create_checkout(offer_key: str, request: Request) -> dict[str, str]:
        user = _request_user(request)
        active_gateway = _require_gateway(gateway)
        try:
            checkout = await active_gateway.create_checkout(
                user_id=user.id,
                email=user.email,
                offer_key=offer_key,
            )
        except PaddleCheckoutConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except PaddleApiError as exc:
            raise HTTPException(status_code=502, detail="payment provider request failed") from exc
        return {
            "provider": PADDLE_PROVIDER,
            "transaction_ref": checkout.transaction_ref,
            "checkout_url": checkout.checkout_url,
        }

    @router.post("/series/{canonical_series_id}/checkout")
    async def create_series_checkout(
        canonical_series_id: UUID,
        request: Request,
    ) -> dict[str, str]:
        user = _request_user(request)
        active_gateway = _require_series_gateway(series_gateway)
        try:
            checkout = await active_gateway.create_checkout(
                user_id=user.id,
                email=user.email,
                canonical_series_id=canonical_series_id,
            )
        except SeriesPassCheckoutConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except PaddleApiError as exc:
            raise HTTPException(status_code=502, detail="payment provider request failed") from exc
        return {
            "provider": PADDLE_PROVIDER,
            "transaction_ref": checkout.transaction_ref,
            "checkout_url": checkout.checkout_url,
            "canonical_series_id": str(canonical_series_id),
        }

    @router.post("/portal")
    async def create_portal(request: Request) -> dict[str, str]:
        user = _request_user(request)
        active_gateway = _require_gateway(gateway)
        try:
            portal_url = await active_gateway.create_portal_url(user_id=user.id)
        except PaddleApiError as exc:
            raise HTTPException(status_code=502, detail="payment provider request failed") from exc
        if portal_url is None:
            raise HTTPException(status_code=404, detail="no Paddle billing account exists yet")
        return {"provider": PADDLE_PROVIDER, "portal_url": portal_url}

    @router.post("/webhooks/paddle")
    async def paddle_webhook(request: Request) -> dict[str, Any]:
        if gateway is None and series_gateway is None:
            raise HTTPException(status_code=503, detail="Paddle billing is disabled")
        raw_body = await _bounded_request_body(request, max_bytes=_MAX_PADDLE_WEBHOOK_BYTES)
        signature = request.headers.get("paddle-signature")
        global_result = None
        series_result = None
        try:
            if gateway is not None:
                global_result = await gateway.process_webhook(
                    raw_body=raw_body,
                    signature_header=signature,
                )
            if series_gateway is not None:
                series_result = await series_gateway.process_webhook(
                    raw_body=raw_body,
                    signature_header=signature,
                )
            # PromotionService intentionally does not trust signatures itself.
            # It runs only after at least one configured Paddle adapter verified
            # this exact raw body and completed its ownership reconciliation.
            await referral_service.handle_paddle_payment_event(raw_body)
        except PaddleWebhookSignatureError as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
        except PaddleWebhookError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail="billing event conflict") from exc

        result = _combined_webhook_result(global_result, series_result)
        return {
            "ok": True,
            **result,
        }

    return router


async def _bounded_request_body(request: Request, *, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail="Paddle webhook body is too large",
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _combined_webhook_result(global_result, series_result) -> dict[str, Any]:
    candidates = [item for item in (global_result, series_result) if item is not None]
    if not candidates:
        return {
            "event_ref": None,
            "event_type": None,
            "ignored": True,
            "duplicate": False,
            "stale": False,
        }
    applied = next((item for item in candidates if not item.ignored), candidates[0])
    return {
        "event_ref": applied.event_ref,
        "event_type": applied.event_type,
        "ignored": all(item.ignored for item in candidates),
        "duplicate": any(item.duplicate for item in candidates),
        "stale": any(item.stale for item in candidates),
    }


def _configured_offers(settings: Settings) -> tuple[PaddleOffer, ...]:
    result: list[PaddleOffer] = []
    if settings.paddle_pro_monthly_price_id.strip():
        result.append(
            PaddleOffer(
                key="pro_monthly",
                label="Pro Monthly",
                price_id=settings.paddle_pro_monthly_price_id.strip(),
                recurring=True,
                grant_days=None,
                supports_alipay=True,
                supports_wechat_pay=False,
            )
        )
    if settings.paddle_pro_30d_price_id.strip():
        result.append(
            PaddleOffer(
                key="pro_30d",
                label="Pro 30-day Pass",
                price_id=settings.paddle_pro_30d_price_id.strip(),
                recurring=False,
                grant_days=30,
                supports_alipay=True,
                supports_wechat_pay=True,
            )
        )
    if settings.paddle_pro_365d_price_id.strip():
        result.append(
            PaddleOffer(
                key="pro_365d",
                label="Pro 365-day Pass",
                price_id=settings.paddle_pro_365d_price_id.strip(),
                recurring=False,
                grant_days=365,
                supports_alipay=True,
                supports_wechat_pay=True,
            )
        )
    return tuple(result)


def _gateway(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    offers: tuple[PaddleOffer, ...],
) -> PaddleBillingGateway | None:
    if not settings.paddle_enabled:
        return None
    if settings.paddle_configuration_errors:
        missing = ", ".join(settings.paddle_configuration_errors)
        raise RuntimeError(f"Paddle billing configuration is incomplete: {missing}")
    if settings.paddle_api_key is None or settings.paddle_webhook_secret is None:
        raise RuntimeError("validated Paddle billing configuration is incomplete")
    return PaddleBillingGateway(
        session_factory=session_factory,
        api_key=settings.paddle_api_key.get_secret_value(),
        webhook_secret=settings.paddle_webhook_secret.get_secret_value(),
        api_base_url=settings.paddle_api_base_url,
        offers=offers,
        checkout_url=settings.paddle_checkout_url,
        api_timeout_seconds=settings.paddle_timeout_seconds,
        webhook_tolerance_seconds=settings.paddle_webhook_tolerance_seconds,
    )


def _series_gateway(
    settings: Settings,
    promotions: PromotionSettings,
    session_factory: async_sessionmaker[AsyncSession],
) -> PaddleSeriesPassService | None:
    if not settings.paddle_enabled or not promotions.series_pass_enabled:
        return None
    if settings.paddle_configuration_errors:
        missing = ", ".join(settings.paddle_configuration_errors)
        raise RuntimeError(f"Paddle billing configuration is incomplete: {missing}")
    if settings.paddle_api_key is None or settings.paddle_webhook_secret is None:
        raise RuntimeError("validated Paddle billing configuration is incomplete")
    return PaddleSeriesPassService(
        session_factory,
        api_key=settings.paddle_api_key.get_secret_value(),
        webhook_secret=settings.paddle_webhook_secret.get_secret_value(),
        api_base_url=settings.paddle_api_base_url,
        price_id=promotions.paddle_series_pass_price_id,
        access_days=promotions.paddle_series_pass_access_days,
        checkout_url=settings.paddle_checkout_url,
        api_timeout_seconds=settings.paddle_timeout_seconds,
        webhook_tolerance_seconds=settings.paddle_webhook_tolerance_seconds,
    )


def _promotion_service(
    session_factory: async_sessionmaker[AsyncSession],
    settings: PromotionSettings,
) -> PromotionService:
    return PromotionService(
        session_factory,
        referral_enabled=settings.referral_enabled,
        campaign_key=settings.referral_campaign_key,
        claim_window_days=settings.referral_claim_window_days,
        inviter_reward_days=settings.referral_inviter_reward_days,
        invited_reward_days=settings.referral_invited_reward_days,
        max_rewards_per_inviter=settings.referral_max_rewards_per_inviter,
    )


def _request_user(request: Request) -> AuthenticatedUser:
    user = getattr(request.state, "auth_user", None)
    if not isinstance(user, AuthenticatedUser):
        raise HTTPException(status_code=401, detail="authentication required")
    return user


def _require_gateway(gateway: PaddleBillingGateway | None) -> PaddleBillingGateway:
    if gateway is None:
        raise HTTPException(status_code=503, detail="Paddle billing is disabled")
    return gateway


def _require_series_gateway(
    gateway: PaddleSeriesPassService | None,
) -> PaddleSeriesPassService:
    if gateway is None:
        raise HTTPException(status_code=503, detail="series pass billing is disabled")
    return gateway
