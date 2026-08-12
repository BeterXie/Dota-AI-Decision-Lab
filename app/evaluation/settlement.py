from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import MapResultEvidenceRecord, MapResultRecord
from app.time import earliest


class SettlementService:
    async def settle(
        self,
        session: AsyncSession,
        *,
        canonical_map_id: UUID,
        winner_team_id: UUID | None,
        provider: str,
        provider_match_id: str,
        result_observed_at: datetime,
        basic_first_usable_at: datetime,
        raw_event_id: UUID,
        normalizer_version: str,
        identity_confidence: float,
        advanced_first_usable_at: datetime | None = None,
        provider_conflict: bool = False,
    ) -> MapResultRecord:
        if not 0 <= identity_confidence <= 1:
            raise ValueError("result identity confidence must be between zero and one")
        evidence = await session.scalar(
            select(MapResultEvidenceRecord).where(
                MapResultEvidenceRecord.canonical_map_id == canonical_map_id,
                MapResultEvidenceRecord.raw_event_id == raw_event_id,
            )
        )
        if evidence is None:
            evidence = MapResultEvidenceRecord(
                canonical_map_id=canonical_map_id,
                provider=provider,
                provider_match_id=provider_match_id,
                winner_team_id=winner_team_id,
                result_observed_at=result_observed_at,
                first_usable_at=basic_first_usable_at,
                raw_event_id=raw_event_id,
                normalizer_version=normalizer_version,
                identity_confidence=identity_confidence,
                conflict_status="DATA_CONFLICT" if provider_conflict else "CONFIRMED",
            )
            session.add(evidence)
            await session.flush()
        record = await session.scalar(
            select(MapResultRecord).where(MapResultRecord.canonical_map_id == canonical_map_id)
        )
        evidence_rows = list(
            (
                await session.scalars(
                    select(MapResultEvidenceRecord).where(
                        MapResultEvidenceRecord.canonical_map_id == canonical_map_id
                    )
                )
            ).all()
        )
        winners = {item.winner_team_id for item in evidence_rows if item.winner_team_id}
        conflict = (
            provider_conflict
            or len(winners) > 1
            or any(item.conflict_status == "DATA_CONFLICT" for item in evidence_rows)
        )
        resolved_winner = next(iter(winners)) if len(winners) == 1 and not conflict else None
        for item in evidence_rows:
            item.conflict_status = "DATA_CONFLICT" if conflict else "CONFIRMED"
        if record is None:
            record = MapResultRecord(
                canonical_map_id=canonical_map_id,
                winner_team_id=resolved_winner,
                basic_first_usable_at=basic_first_usable_at,
                advanced_first_usable_at=advanced_first_usable_at,
                provider_conflict=conflict,
            )
            session.add(record)
            await session.flush()
            return record
        record.provider_conflict = conflict
        record.winner_team_id = resolved_winner
        record.basic_first_usable_at = earliest(record.basic_first_usable_at, basic_first_usable_at)
        if advanced_first_usable_at is not None:
            record.advanced_first_usable_at = (
                earliest(record.advanced_first_usable_at, advanced_first_usable_at)
                if record.advanced_first_usable_at is not None
                else advanced_first_usable_at
            )
        return record
