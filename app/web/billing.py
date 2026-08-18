from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth import AuthenticatedUser
from app.billing.paddle import (
    PADDLE_PROVIDER,
    PaddleApiError,
    PaddleWebhookError,
    PaddleWebhookSignatureError,
)
from app.config import Settings
from app.entitlements import EntitlementService
from app.promotions import PromotionService
from app.promotions.config import PromotionSettings
from app.promotions.models import CompetitionPassPurchaseRecord
from app.promotions.paddle_event import PaddleEventPassService
from app.promotions.paddle_pass import CompetitionPassCheckoutConflict
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
    series_gateway = _pass_gateway(
        settings,
        session_factory,
        scope_type="SERIES",
        price_id=settings.paddle_series_pass_price_id,
    )
    event_gateway = _pass_gateway(
        settings,
        session_factory,
        scope_type="EVENT",
        price_id=settings.paddle_event_pass_price_id,
    )
    entitlements = EntitlementService(session_factory)

    @router.get("/offers")
    async def billing_offers() -> dict[str, Any]:
        return {
            "provider": PADDLE_PROVIDER,
            "enabled": series_gateway is not None or event_gateway is not None,
            "environment": settings.paddle_environment,
            "series_pass": (
                series_gateway.public_offer
                if series_gateway is not None
                else {"enabled": False}
            ),
            "event_pass": (
                event_gateway.public_offer
                if event_gateway is not None
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
            passes = list(
                (
                    await session.scalars(
                        select(CompetitionPassPurchaseRecord)
                        .where(CompetitionPassPurchaseRecord.user_id == user.id)
                        .order_by(CompetitionPassPurchaseRecord.created_at.desc())
                        .limit(50)
                    )
                ).all()
            )
        return {
            "entitlements": list(await entitlements.active_entitlements(user.id)),
            "grants": [item.public_payload() for item in await entitlements.active_grants(user.id)],
            "passes": [
                {
                    "provider": item.provider,
                    "scope_type": item.scope_type,
                    "canonical_series_id": (
                        str(item.canonical_series_id)
                        if item.canonical_series_id is not None
                        else None
                    ),
                    "canonical_event_id": (
                        str(item.canonical_event_id)
                        if item.canonical_event_id is not None
                        else None
                    ),
                    "status": item.status,
                    "completed_at": item.completed_at,
                    "payment_blocked": item.payment_blocked,
                    }
                for item in passes
            ],
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
        except CompetitionPassCheckoutConflict as exc:
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

    @router.post("/events/{canonical_event_id}/checkout")
    async def create_event_checkout(
        canonical_event_id: UUID,
        request: Request,
    ) -> dict[str, str]:
        user = _request_user(request)
        active_gateway = _require_event_gateway(event_gateway)
        try:
            checkout = await active_gateway.create_checkout(
                user_id=user.id,
                email=user.email,
                canonical_event_id=canonical_event_id,
            )
        except CompetitionPassCheckoutConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except PaddleApiError as exc:
            raise HTTPException(status_code=502, detail="payment provider request failed") from exc
        return {
            "provider": PADDLE_PROVIDER,
            "transaction_ref": checkout.transaction_ref,
            "checkout_url": checkout.checkout_url,
            "canonical_event_id": str(canonical_event_id),
        }

    @router.post("/webhooks/paddle")
    async def paddle_webhook(request: Request) -> dict[str, Any]:
        if series_gateway is None and event_gateway is None:
            raise HTTPException(status_code=503, detail="Paddle billing is disabled")
        raw_body = await _bounded_request_body(request, max_bytes=_MAX_PADDLE_WEBHOOK_BYTES)
        signature = request.headers.get("paddle-signature")
        series_result = None
        event_result = None
        try:
            if series_gateway is not None:
                series_result = await series_gateway.process_webhook(
                    raw_body=raw_body,
                    signature_header=signature,
                )
            if event_gateway is not None:
                event_result = await event_gateway.process_webhook(
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

        result = _combined_webhook_result(series_result, event_result)
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


def _combined_webhook_result(*results) -> dict[str, Any]:
    candidates = [item for item in results if item is not None]
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


def _pass_gateway(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    scope_type: str,
    price_id: str,
):
    if not settings.paddle_enabled or not price_id.strip():
        return None
    if settings.paddle_configuration_errors:
        missing = ", ".join(settings.paddle_configuration_errors)
        raise RuntimeError(f"Paddle billing configuration is incomplete: {missing}")
    if settings.paddle_api_key is None or settings.paddle_webhook_secret is None:
        raise RuntimeError("validated Paddle billing configuration is incomplete")
    service_type = PaddleSeriesPassService if scope_type == "SERIES" else PaddleEventPassService
    return service_type(
        session_factory,
        api_key=settings.paddle_api_key.get_secret_value(),
        webhook_secret=settings.paddle_webhook_secret.get_secret_value(),
        api_base_url=settings.paddle_api_base_url,
        price_id=price_id,
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


def _require_series_gateway(
    gateway: PaddleSeriesPassService | None,
) -> PaddleSeriesPassService:
    if gateway is None:
        raise HTTPException(status_code=503, detail="series pass billing is disabled")
    return gateway


def _require_event_gateway(
    gateway: PaddleEventPassService | None,
) -> PaddleEventPassService:
    if gateway is None:
        raise HTTPException(status_code=503, detail="event pass billing is disabled")
    return gateway
