from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth import AuthenticatedUser
from app.entitlements import AI_DECISIONS_ENTITLEMENT, EntitlementService
from app.models import CanonicalMap
from app.web.api import _map_payload


def create_premium_router(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    live_state_max_age_seconds: float,
    live_market_max_age_seconds: float,
    market_max_pair_skew_seconds: float,
) -> APIRouter:
    router = APIRouter()
    entitlements = EntitlementService(session_factory)

    @router.get("/api/maps/{canonical_map_id}/ai-decisions")
    async def map_ai_decisions(canonical_map_id: UUID, request: Request) -> dict:
        user = _request_user(request)
        async with session_factory() as session:
            record = await session.get(CanonicalMap, canonical_map_id)
            if record is None:
                raise HTTPException(status_code=404, detail="map not found")
            allowed = await entitlements.has_resource_entitlement(
                user.id,
                AI_DECISIONS_ENTITLEMENT,
                canonical_series_id=record.series_id,
                canonical_map_id=record.id,
            )
            if not allowed:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="AI Decision access is not granted for this match",
                )
            payload = await _map_payload(
                session,
                record,
                detailed=True,
                live_state_max_age_seconds=live_state_max_age_seconds,
                live_market_max_age_seconds=live_market_max_age_seconds,
                market_max_pair_skew_seconds=market_max_pair_skew_seconds,
            )
        return {
            "canonical_map_id": str(canonical_map_id),
            "canonical_series_id": str(record.series_id) if record.series_id is not None else None,
            "latest_snapshot": payload.get("latest_snapshot"),
            "decisions": payload.get("decisions", []),
            "checkpoint_decisions": payload.get("checkpoint_decisions", []),
            "snapshot_payload": payload.get("snapshot_payload"),
            "future_odds": payload.get("future_odds", []),
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
