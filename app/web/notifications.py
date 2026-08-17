from uuid import UUID

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


class NotificationPreferencePayload(BaseModel):
    enabled: bool


def create_notification_router(
    session_factory: async_sessionmaker[AsyncSession],
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
        return {
            "channel": normalized,
            "code": code,
            "command": f"绑定 {code}",
            "expires_at": expires_at,
        }

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
        if not await center.disable_binding(user.id, binding_id):
            raise HTTPException(status_code=404, detail="notification binding not found")
        return await center.overview(user.id)

    return router


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
