from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.evaluation.leaderboard import TournamentLeaderboardService
from app.evaluation.portfolio_models import (
    TournamentPortfolioAccountRecord,
    TournamentPortfolioPositionRecord,
)
from app.evaluation.quality import TournamentQualityService
from app.models import CanonicalEvent, CanonicalMap


async def build_position_audit(
    session: AsyncSession,
    *,
    canonical_event_id: UUID,
    account_id: UUID,
) -> dict[str, Any] | None:
    account = await session.scalar(
        select(TournamentPortfolioAccountRecord).where(
            TournamentPortfolioAccountRecord.id == account_id,
            TournamentPortfolioAccountRecord.canonical_event_id == canonical_event_id,
        )
    )
    if account is None:
        return None
    rows = list(
        (
            await session.execute(
                select(TournamentPortfolioPositionRecord, CanonicalMap)
                .join(
                    CanonicalMap,
                    CanonicalMap.id == TournamentPortfolioPositionRecord.canonical_map_id,
                )
                .where(TournamentPortfolioPositionRecord.portfolio_account_id == account_id)
                .order_by(
                    TournamentPortfolioPositionRecord.opened_at.desc(),
                    TournamentPortfolioPositionRecord.id,
                )
            )
        ).all()
    )
    return {
        "canonical_event_id": str(canonical_event_id),
        "account_id": str(account_id),
        "experiment": {
            "provider": account.provider,
            "model": account.model,
            "prompt_version": account.prompt_version,
            "decision_policy_version": account.decision_policy_version,
            "ai_view_version": account.ai_view_version,
        },
        "positions": [
            {
                "id": str(position.id),
                "ai_decision_id": str(position.ai_decision_id),
                "canonical_series_id": str(position.canonical_series_id),
                "canonical_map_id": str(position.canonical_map_id),
                "map_number": canonical_map.map_number,
                "action": position.action,
                "cash_before": float(position.cash_before),
                "stake": float(position.stake),
                "odds": float(position.odds) if position.odds is not None else None,
                "status": position.status,
                "rejection_reason": position.rejection_reason,
                "payout": float(position.payout) if position.payout is not None else None,
                "realized_pnl": (
                    float(position.realized_pnl)
                    if position.realized_pnl is not None
                    else None
                ),
                "opened_at": position.opened_at,
                "settled_at": position.settled_at,
            }
            for position, canonical_map in rows
        ],
    }


def create_quality_router(
    session_factory: async_sessionmaker[AsyncSession],
) -> APIRouter:
    router = APIRouter()
    quality = TournamentQualityService()
    leaderboard = TournamentLeaderboardService()

    @router.get("/api/review/ai-quality/leaderboard")
    async def global_ai_quality_leaderboard() -> dict[str, Any]:
        async with session_factory() as session:
            return await leaderboard.build_report(session)

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

    @router.get("/api/review/events/{canonical_event_id}/ai-quality/positions")
    async def event_ai_quality_positions(
        canonical_event_id: UUID,
        account_id: UUID,
    ) -> dict[str, Any]:
        async with session_factory() as session:
            payload = await build_position_audit(
                session,
                canonical_event_id=canonical_event_id,
                account_id=account_id,
            )
            if payload is None:
                raise HTTPException(status_code=404, detail="portfolio account not found")
            return payload

    return router
