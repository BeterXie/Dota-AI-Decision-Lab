from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.evaluation.quality import TournamentQualityService
from app.models import CanonicalEvent


def create_quality_router(
    session_factory: async_sessionmaker[AsyncSession],
) -> APIRouter:
    router = APIRouter()
    quality = TournamentQualityService()

    @router.get("/api/review/events/{canonical_event_id}/ai-quality")
    async def event_ai_quality(canonical_event_id: UUID) -> dict[str, Any]:
        async with session_factory() as session:
            event = await session.get(CanonicalEvent, canonical_event_id)
            if event is None:
                raise HTTPException(status_code=404, detail="canonical event not found")
            return await quality.build_report(
                session,
                canonical_event_id=canonical_event_id,
            )

    return router
