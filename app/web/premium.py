from uuid import UUID

from fastapi import APIRouter, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

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

    @router.get("/api/maps/{canonical_map_id}/ai-decisions")
    async def map_ai_decisions(canonical_map_id: UUID) -> dict:
        async with session_factory() as session:
            record = await session.get(CanonicalMap, canonical_map_id)
            if record is None:
                raise HTTPException(status_code=404, detail="map not found")
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
            "latest_snapshot": payload.get("latest_snapshot"),
            "decisions": payload.get("decisions", []),
            "checkpoint_decisions": payload.get("checkpoint_decisions", []),
            "snapshot_payload": payload.get("snapshot_payload"),
            "future_odds": payload.get("future_odds", []),
        }

    return router
