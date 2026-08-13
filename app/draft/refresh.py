from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.jobs import JobType
from app.draft.data_repair import repair_legacy_drafts
from app.jobs.repository import JobRepository
from app.models import CanonicalMap, DltvLiveObservationRecord, DraftSnapshotRecord


@dataclass(frozen=True)
class DraftRefreshResult:
    active_maps: int
    enqueued: int


async def schedule_incomplete_draft_refreshes(
    session: AsyncSession,
    jobs: JobRepository,
    *,
    interval_seconds: float,
    now: datetime | None = None,
    active_window: timedelta = timedelta(minutes=15),
    recovery_window: timedelta = timedelta(hours=6),
) -> DraftRefreshResult:
    await repair_legacy_drafts(session)
    current = now or datetime.now(UTC)
    active_map_ids = set(
        (
            await session.scalars(
                select(DltvLiveObservationRecord.canonical_map_id).where(
                    DltvLiveObservationRecord.canonical_map_id.is_not(None),
                    DltvLiveObservationRecord.received_at >= current - active_window,
                )
            )
        ).all()
    )
    incomplete_map_ids = set(
        (
            await session.scalars(
                select(DraftSnapshotRecord.canonical_map_id).where(
                    DraftSnapshotRecord.complete.is_(False),
                    DraftSnapshotRecord.observed_at >= current - recovery_window,
                )
            )
        ).all()
    )
    candidate_map_ids = active_map_ids | incomplete_map_ids
    maps = list(
        (
            await session.scalars(
                select(CanonicalMap).where(
                    CanonicalMap.id.in_(candidate_map_ids),
                    CanonicalMap.valve_match_id.is_not(None),
                )
            )
        ).all()
    )
    bucket = int(current.timestamp() // interval_seconds)
    enqueued = 0
    for canonical_map in maps:
        latest_complete = await session.scalar(
            select(DraftSnapshotRecord.complete)
            .where(DraftSnapshotRecord.canonical_map_id == canonical_map.id)
            .order_by(DraftSnapshotRecord.observed_at.desc())
            .limit(1)
        )
        if latest_complete is True:
            continue
        await jobs.enqueue(
            session,
            job_type=JobType.BOOTSTRAP_DLTV_MATCH,
            dedupe_key=f"periodic-dltv-draft:{canonical_map.valve_match_id}:{bucket}",
            payload={"valve_match_id": canonical_map.valve_match_id},
            priority=25,
        )
        enqueued += 1
    return DraftRefreshResult(active_maps=len(active_map_ids), enqueued=enqueued)
