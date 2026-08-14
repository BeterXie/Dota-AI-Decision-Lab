from uuid import UUID

from fastapi import FastAPI, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.history.service import HistoricalIntelligenceService
from app.models import CanonicalMap, DraftSlotRecord, DraftSnapshotRecord


HERO_RECENT_WINDOW = 10


def register_player_hero_recent_routes(
    app: FastAPI,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    @app.get("/api/maps/{canonical_map_id}/draft-hero-recent")
    async def draft_hero_recent(canonical_map_id: UUID) -> dict:
        async with session_factory() as session:
            canonical_map = await session.get(CanonicalMap, canonical_map_id)
            if canonical_map is None:
                raise HTTPException(status_code=404, detail="map not found")

            draft = await session.scalar(
                select(DraftSnapshotRecord)
                .where(DraftSnapshotRecord.canonical_map_id == canonical_map_id)
                .order_by(DraftSnapshotRecord.observed_at.desc())
                .limit(1)
            )
            if draft is None:
                return {
                    "canonical_map_id": str(canonical_map_id),
                    "statistics_cutoff": None,
                    "window": HERO_RECENT_WINDOW,
                    "slots": [],
                }

            slots = list(
                (
                    await session.scalars(
                        select(DraftSlotRecord)
                        .where(DraftSlotRecord.draft_snapshot_id == draft.id)
                        .order_by(DraftSlotRecord.side, DraftSlotRecord.position)
                    )
                ).all()
            )
            historical = HistoricalIntelligenceService()
            payload_slots: list[dict] = []
            for slot in slots:
                recent = None
                if slot.canonical_player_id is not None and slot.hero_id is not None:
                    recent = await historical.get_player_hero_recent_uses(
                        session,
                        slot.canonical_player_id,
                        hero_id=slot.hero_id,
                        as_of=draft.statistics_cutoff,
                        limit=HERO_RECENT_WINDOW,
                    )
                payload_slots.append(
                    {
                        "side": slot.side,
                        "position": slot.position,
                        "canonical_player_id": (
                            str(slot.canonical_player_id)
                            if slot.canonical_player_id is not None
                            else None
                        ),
                        "hero_id": slot.hero_id,
                        "recent": recent,
                    }
                )

            return {
                "canonical_map_id": str(canonical_map_id),
                "statistics_cutoff": draft.statistics_cutoff,
                "window": HERO_RECENT_WINDOW,
                "slots": payload_slots,
            }
