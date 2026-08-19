from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.access_policy import resolve_map_access
from app.auth import AuthenticatedUser
from app.entitlements import EntitlementService


def create_access_router(
    session_factory: async_sessionmaker[AsyncSession],
    entitlements: EntitlementService,
) -> APIRouter:
    router = APIRouter(prefix="/api/access", tags=["access"])

    @router.get("/maps/{canonical_map_id}")
    async def map_access(canonical_map_id: UUID, request: Request) -> dict:
        user = _optional_request_user(request)
        async with session_factory() as session:
            access = await resolve_map_access(
                session,
                entitlements,
                canonical_map_id,
                user=user,
            )
        if access is None:
            raise HTTPException(status_code=404, detail="map not found")
        return {
            "canonical_map_id": str(access.canonical_map.id),
            "canonical_series_id": (
                str(access.canonical_map.series_id)
                if access.canonical_map.series_id is not None
                else None
            ),
            "stage_key": access.series.stage_key if access.series is not None else "UNKNOWN",
            "ai_decisions": {
                "allowed": access.ai_allowed,
                "scope": access.ai_scope,
                "public_projection": access.ai_public_projection,
            },
            "realtime_notifications": {
                "allowed": access.notification_allowed,
                "scope": access.notification_scope,
            },
        }

    return router


def _optional_request_user(request: Request) -> AuthenticatedUser | None:
    user = getattr(request.state, "auth_user", None)
    return user if isinstance(user, AuthenticatedUser) else None
