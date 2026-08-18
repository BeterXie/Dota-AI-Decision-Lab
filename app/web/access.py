from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth import AuthenticatedUser
from app.domain.competition import is_group_stage
from app.entitlements import (
    AI_DECISIONS_ENTITLEMENT,
    REALTIME_NOTIFICATIONS_ENTITLEMENT,
    EntitlementService,
)
from app.models import CanonicalMap, CanonicalSeries


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
            series = (
                await session.get(CanonicalSeries, canonical_map.series_id)
                if canonical_map is not None and canonical_map.series_id is not None
                else None
            )
        if canonical_map is None:
            raise HTTPException(status_code=404, detail="map not found")
        ai_scope = await entitlements.access_scope(
            user.id,
            AI_DECISIONS_ENTITLEMENT,
            canonical_event_id=series.event_id if series is not None else None,
            canonical_series_id=canonical_map.series_id,
            canonical_map_id=canonical_map.id,
        )
        notification_scope = await entitlements.access_scope(
            user.id,
            REALTIME_NOTIFICATIONS_ENTITLEMENT,
            canonical_event_id=series.event_id if series is not None else None,
            canonical_series_id=canonical_map.series_id,
            canonical_map_id=canonical_map.id,
        )
        ai_allowed = is_group_stage(series.stage_key) if series is not None else False
        if ai_allowed:
            ai_scope = "FREE"
        return {
            "canonical_map_id": str(canonical_map.id),
            "canonical_series_id": (
                str(canonical_map.series_id) if canonical_map.series_id is not None else None
            ),
            "stage_key": series.stage_key if series is not None else "UNKNOWN",
            "ai_decisions": {"allowed": ai_allowed or ai_scope is not None, "scope": ai_scope},
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
