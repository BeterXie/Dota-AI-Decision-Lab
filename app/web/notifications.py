from collections.abc import Awaitable, Callable
from typing import Protocol
from uuid import UUID

import structlog
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth import AuthenticatedUser
from app.entitlements import REALTIME_NOTIFICATIONS_ENTITLEMENT, EntitlementService
from app.notifications.center import (
    PAIRABLE_CHANNELS,
    NotificationBindingConflict,
    normalize_channel,
)
from app.notifications.secure_center import NotificationCenterService

QQPairingLinkFactory = Callable[[str], Awaitable[str]]
logger = structlog.get_logger()


class UserQrBindingService(Protocol):
    async def start(self, owner_user_id: UUID) -> dict: ...

    async def poll(
        self,
        owner_user_id: UUID,
        session_id: str,
        *,
        verify_code: str | None = None,
    ) -> dict: ...

    async def cancel(self, owner_user_id: UUID, session_id: str) -> dict: ...

    async def revoke(self, owner_user_id: UUID, destination: dict) -> None: ...


class QrVerifyPayload(BaseModel):
    verify_code: str | None = None


class NotificationPreferencePayload(BaseModel):
    enabled: bool


def create_notification_router(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    qq_pairing_link_factory: QQPairingLinkFactory | None = None,
    qq_contact_url: str | None = None,
    wechat_contact_url: str | None = None,
    qq_qr_binding_service: UserQrBindingService | None = None,
    wechat_qr_binding_service: UserQrBindingService | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/notifications", tags=["notifications"])
    center = NotificationCenterService(session_factory)
    entitlements = EntitlementService(session_factory)

    @router.get("")
    async def notification_center(request: Request) -> dict:
        user = await _request_user(request, entitlements)
        return await center.overview(user.id)

    @router.post("/bindings/email")
    async def bind_verified_email(request: Request) -> dict:
        user = await _request_user(request, entitlements)
        try:
            await center.ensure_email_binding(
                user_id=user.id,
                email=user.email,
                verified_at=user.email_verified_at,
            )
        except NotificationBindingConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return await center.overview(user.id)

    @router.post("/pairing/{channel}")
    async def create_pairing(channel: str, request: Request) -> dict:
        user = await _request_user(request, entitlements)
        try:
            normalized = normalize_channel(channel)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if normalized not in PAIRABLE_CHANNELS:
            raise HTTPException(
                status_code=422, detail="pairing is only supported for QQ and WeChat"
            )
        code, expires_at = await center.create_pairing_code(user.id, normalized)
        share_url = None
        contact_url = None
        pairing_mode = "MANUAL_MESSAGE"
        if normalized == "QQ":
            contact_url = qq_contact_url
            if qq_pairing_link_factory is not None:
                try:
                    share_url = await qq_pairing_link_factory(code)
                    pairing_mode = "QQ_SHARE_LINK"
                except Exception:
                    # The code remains valid; the user can use the configured
                    # fallback contact link or send it in an existing chat.
                    share_url = None
            if share_url is None and contact_url:
                pairing_mode = "QQ_CONTACT_LINK"
        else:
            contact_url = wechat_contact_url
            if contact_url:
                pairing_mode = "WECHAT_CONTACT_LINK"
        return {
            "channel": normalized,
            "code": code,
            "command": f"绑定 {code}",
            "expires_at": expires_at,
            "share_url": share_url,
            "contact_url": contact_url,
            "pairing_mode": pairing_mode,
        }

    @router.post("/qr/{channel}/start")
    async def start_qr_binding(channel: str, request: Request) -> dict:
        user = await _request_user(request, entitlements)
        service = _qr_service(channel, qq_qr_binding_service, wechat_qr_binding_service)
        if service is None:
            raise HTTPException(status_code=503, detail="QR account binding is not configured")
        try:
            return await service.start(user.id)
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=f"unable to start QR binding: {exc}",
            ) from exc

    @router.post("/qr/{channel}/{session_id}")
    async def poll_qr_binding(
        channel: str,
        session_id: str,
        request: Request,
        payload: QrVerifyPayload | None = None,
    ) -> dict:
        user = await _request_user(request, entitlements)
        service = _qr_service(channel, qq_qr_binding_service, wechat_qr_binding_service)
        if service is None:
            raise HTTPException(status_code=503, detail="QR account binding is not configured")
        try:
            return await service.poll(
                user.id,
                session_id,
                verify_code=payload.verify_code if payload else None,
            )
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.delete("/qr/{channel}/{session_id}")
    async def cancel_qr_binding(channel: str, session_id: str, request: Request) -> dict:
        user = await _request_user(request, entitlements)
        service = _qr_service(channel, qq_qr_binding_service, wechat_qr_binding_service)
        if service is None:
            raise HTTPException(status_code=503, detail="QR account binding is not configured")
        try:
            return await service.cancel(user.id, session_id)
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.put("/preferences/{channel}")
    async def update_preference(
        channel: str,
        payload: NotificationPreferencePayload,
        request: Request,
    ) -> dict:
        user = await _request_user(request, entitlements)
        try:
            normalized = normalize_channel(channel)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        await center.set_preference(user.id, normalized, enabled=payload.enabled)
        return await center.overview(user.id)

    @router.delete("/bindings/{binding_id}")
    async def disable_binding(binding_id: UUID, request: Request) -> dict:
        user = await _request_user(request, entitlements)
        binding_info = await center.binding_destination(user.id, binding_id)
        if binding_info is None:
            raise HTTPException(status_code=404, detail="notification binding not found")
        channel, destination = binding_info
        if not await center.disable_binding(user.id, binding_id):
            raise HTTPException(status_code=404, detail="notification binding not found")
        if channel in PAIRABLE_CHANNELS:
            service = _qr_service(channel, qq_qr_binding_service, wechat_qr_binding_service)
            revoke = getattr(service, "revoke", None)
            if callable(revoke):
                try:
                    await revoke(user.id, destination)
                except Exception as exc:
                    # The binding is already disabled in the durable ledger. A
                    # transient provider-state cleanup failure must not resurrect
                    # delivery; the next account refresh can remove the token.
                    logger.warning(
                        "notification_provider_binding_cleanup_failed",
                        channel=channel,
                        binding_id=str(binding_id),
                        error_type=type(exc).__name__,
                    )
        return await center.overview(user.id)

    return router


def _qr_service(
    channel: str,
    qq_service: UserQrBindingService | None,
    wechat_service: UserQrBindingService | None,
) -> UserQrBindingService | None:
    try:
        normalized = normalize_channel(channel)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if normalized == "QQ":
        return qq_service
    if normalized == "WECHAT":
        return wechat_service
    raise HTTPException(
        status_code=422,
        detail="QR account binding is only available for QQ and WeChat",
    )


async def _request_user(
    request: Request,
    entitlements: EntitlementService,
) -> AuthenticatedUser:
    user = getattr(request.state, "auth_user", None)
    if not isinstance(user, AuthenticatedUser):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="authentication required"
        )
    if not await entitlements.has_any_entitlement(
        user.id,
        REALTIME_NOTIFICATIONS_ENTITLEMENT,
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="entitlement required",
            headers={"X-Required-Entitlement": REALTIME_NOTIFICATIONS_ENTITLEMENT},
        )
    return user
