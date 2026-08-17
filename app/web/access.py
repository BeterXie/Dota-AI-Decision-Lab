from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth import AuthenticatedUser
from app.entitlements import (
    AI_DECISIONS_ENTITLEMENT,
    REALTIME_NOTIFICATIONS_ENTITLEMENT,
    EntitlementService,
)
from app.models import CanonicalMap


def create_access_router(
    session_factory: async_sessionmaker[AsyncSession],
    entitlements: EntitlementService,
) -> APIRouter:
    router = APIRouter(prefix="/api/access", tags=["access"])

    @router.get("/maps/{canonical_map_id}")
    async def map_access(canonical_map_id: UUID, request: Request) -> dict:
        user = _request_user(request)
        async with session_factory() as session:
            canonical_map = await session.get(CanonicalMap, canonical_map_id)
        if canonical_map is None:
            raise HTTPException(status_code=404, detail="map not found")
        ai_scope = await entitlements.access_scope(
            user.id,
            AI_DECISIONS_ENTITLEMENT,
            canonical_series_id=canonical_map.series_id,
            canonical_map_id=canonical_map.id,
        )
        notification_scope = await entitlements.access_scope(
            user.id,
            REALTIME_NOTIFICATIONS_ENTITLEMENT,
            canonical_series_id=canonical_map.series_id,
            canonical_map_id=canonical_map.id,
        )
        return {
            "canonical_map_id": str(canonical_map.id),
            "canonical_series_id": (
                str(canonical_map.series_id) if canonical_map.series_id is not None else None
            ),
            "ai_decisions": {"allowed": ai_scope is not None, "scope": ai_scope},
            "realtime_notifications": {
                "allowed": notification_scope is not None,
                "scope": notification_scope,
            },
        }

    return router


def _request_user(request: Request) -> AuthenticatedUser:
    user = getattr(request.state, "auth_user", None)
    if not isinstance(user, AuthenticatedUser):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="authentication required",
        )
    return user
