from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.history.scoring import sample_confidence
from app.models import (
    PlayerFormSnapshotRecord,
    PlayerHeroSnapshotRecord,
    TeamFormSnapshotRecord,
    TeamRatingSnapshotRecord,
)


class HistoricalIntelligenceService:
    async def get_team_payload(
        self,
        session: AsyncSession,
        team_id: UUID,
        *,
        as_of: datetime,
    ) -> dict:
        rating = await session.scalar(
            select(TeamRatingSnapshotRecord)
            .where(
                TeamRatingSnapshotRecord.canonical_team_id == team_id,
                TeamRatingSnapshotRecord.knowledge_cutoff <= as_of,
            )
            .order_by(TeamRatingSnapshotRecord.knowledge_cutoff.desc())
            .limit(1)
        )
        form = await session.scalar(
            select(TeamFormSnapshotRecord)
            .where(
                TeamFormSnapshotRecord.canonical_team_id == team_id,
                TeamFormSnapshotRecord.knowledge_cutoff <= as_of,
            )
            .order_by(TeamFormSnapshotRecord.knowledge_cutoff.desc())
            .limit(1)
        )
        return {
            "base_rating": rating.rating if rating is not None else None,
            "recent_form": form.recent_form if form is not None else None,
            "recent_form_confidence": (
                sample_confidence(form.last_20_maps) if form is not None else None
            ),
            "last_5": _record(form, "last_5_wins", "last_5_maps"),
            "last_10": _record(form, "last_10_wins", "last_10_maps"),
            "last_20": _record(form, "last_20_wins", "last_20_maps"),
            "roster_stability": form.roster_stability if form is not None else None,
            "exact_roster_maps": form.exact_roster_maps if form is not None else None,
            "knowledge_cutoff": max(
                (item.knowledge_cutoff for item in (rating, form) if item is not None),
                default=None,
            ),
        }

    async def get_player_payload(
        self,
        session: AsyncSession,
        player_id: UUID,
        *,
        position: int,
        as_of: datetime,
    ) -> dict:
        snapshot = await session.scalar(
            select(PlayerFormSnapshotRecord)
            .where(
                PlayerFormSnapshotRecord.canonical_player_id == player_id,
                PlayerFormSnapshotRecord.position == position,
                PlayerFormSnapshotRecord.knowledge_cutoff <= as_of,
            )
            .order_by(PlayerFormSnapshotRecord.knowledge_cutoff.desc())
            .limit(1)
        )
        if snapshot is None:
            return {
                "base_strength": None,
                "recent_form": None,
                "confidence": None,
                "knowledge_cutoff": None,
            }
        return {
            "base_strength": snapshot.base_strength,
            "recent_form": snapshot.recent_form,
            "recent_5": snapshot.recent_5,
            "recent_10": snapshot.recent_10,
            "recent_20": snapshot.recent_20,
            "sample_size": snapshot.sample_size,
            "confidence": snapshot.confidence,
            "knowledge_cutoff": snapshot.knowledge_cutoff,
        }

    async def get_player_hero_payload(
        self,
        session: AsyncSession,
        player_id: UUID,
        *,
        hero_id: int,
        position: int,
        as_of: datetime,
    ) -> dict:
        snapshot = await session.scalar(
            select(PlayerHeroSnapshotRecord)
            .where(
                PlayerHeroSnapshotRecord.canonical_player_id == player_id,
                PlayerHeroSnapshotRecord.hero_id == hero_id,
                PlayerHeroSnapshotRecord.position == position,
                PlayerHeroSnapshotRecord.knowledge_cutoff <= as_of,
            )
            .order_by(PlayerHeroSnapshotRecord.knowledge_cutoff.desc())
            .limit(1)
        )
        if snapshot is None:
            return {
                "adjusted_strength": None,
                "confidence": None,
                "knowledge_cutoff": None,
            }
        return {
            "historical_maps": snapshot.historical_maps,
            "historical_win_rate": snapshot.historical_win_rate,
            "historical_performance": snapshot.historical_performance,
            "recent_180d_maps": snapshot.recent_180d_maps,
            "recent_180d_win_rate": snapshot.recent_180d_win_rate,
            "recent_180d_performance": snapshot.recent_180d_performance,
            "current_patch_maps": snapshot.current_patch_maps,
            "current_patch_win_rate": snapshot.current_patch_win_rate,
            "current_patch_performance": snapshot.current_patch_performance,
            "position_fit": snapshot.position_fit,
            "adjusted_strength": snapshot.adjusted_strength,
            "confidence": snapshot.confidence,
            "knowledge_cutoff": snapshot.knowledge_cutoff,
        }


def _record(record, wins_field: str, maps_field: str) -> str | None:
    if record is None:
        return None
    wins = getattr(record, wins_field)
    losses = getattr(record, maps_field) - wins
    return f"{wins}-{losses}"
