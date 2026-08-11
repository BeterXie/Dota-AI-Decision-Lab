from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import MapResultRecord
from app.time import earliest


class SettlementService:
    async def settle(
        self,
        session: AsyncSession,
        *,
        canonical_map_id: UUID,
        winner_team_id: UUID | None,
        basic_first_usable_at: datetime,
        advanced_first_usable_at: datetime | None = None,
        provider_conflict: bool = False,
    ) -> MapResultRecord:
        record = await session.scalar(
            select(MapResultRecord).where(MapResultRecord.canonical_map_id == canonical_map_id)
        )
        if record is None:
            record = MapResultRecord(
                canonical_map_id=canonical_map_id,
                winner_team_id=winner_team_id,
                basic_first_usable_at=basic_first_usable_at,
                advanced_first_usable_at=advanced_first_usable_at,
                provider_conflict=provider_conflict,
            )
            session.add(record)
            await session.flush()
            return record
        if (
            record.winner_team_id is not None
            and winner_team_id is not None
            and record.winner_team_id != winner_team_id
        ):
            record.provider_conflict = True
            record.winner_team_id = None
        elif record.winner_team_id is None and not record.provider_conflict:
            record.winner_team_id = winner_team_id
        record.basic_first_usable_at = earliest(record.basic_first_usable_at, basic_first_usable_at)
        if advanced_first_usable_at is not None:
            record.advanced_first_usable_at = (
                earliest(record.advanced_first_usable_at, advanced_first_usable_at)
                if record.advanced_first_usable_at is not None
                else advanced_first_usable_at
            )
        record.provider_conflict = record.provider_conflict or provider_conflict
        return record
