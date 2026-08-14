from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.jobs import JobType
from app.jobs.repository import JobRepository
from app.models import CanonicalMap, DltvLiveObservationRecord, DraftSlotRecord, DraftSnapshotRecord


@dataclass(frozen=True)
class DraftRefreshResult:
    active_maps: int
    enqueued: int
    legacy_repairs_enqueued: int


async def schedule_incomplete_draft_refreshes(
    session: AsyncSession,
    jobs: JobRepository,
    *,
    interval_seconds: float,
    now: datetime | None = None,
    active_window: timedelta = timedelta(minutes=15),
    recovery_window: timedelta = timedelta(hours=6),
    legacy_repair_cap: int = 100,
) -> DraftRefreshResult:
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
    legacy_slot_map_ids = set(
        (
            await session.scalars(
                select(DraftSnapshotRecord.canonical_map_id)
                .join(
                    DraftSlotRecord,
                    DraftSlotRecord.draft_snapshot_id == DraftSnapshotRecord.id,
                )
                .where(
                    DraftSlotRecord.source == "DLTV_SLOT",
                )
            )
        ).all()
    )
    candidate_map_ids = active_map_ids | incomplete_map_ids | legacy_slot_map_ids
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
    legacy_repairs_enqueued = 0
    for canonical_map in maps:
        latest = await session.scalar(
            select(DraftSnapshotRecord)
            .where(DraftSnapshotRecord.canonical_map_id == canonical_map.id)
            .order_by(DraftSnapshotRecord.observed_at.desc())
            .limit(1)
        )
        latest_has_legacy_slots = False
        if latest is not None:
            latest_has_legacy_slots = bool(
                await session.scalar(
                    select(DraftSlotRecord.id)
                    .where(
                        DraftSlotRecord.draft_snapshot_id == latest.id,
                        DraftSlotRecord.source == "DLTV_SLOT",
                    )
                    .limit(1)
                )
            )
        if latest is not None and latest.complete and not latest_has_legacy_slots:
            continue
        map_is_active = canonical_map.id in active_map_ids
        legacy_complete = latest is not None and latest.complete and latest_has_legacy_slots
        if legacy_complete and not map_is_active:
            # Legacy drafts stored provider ordering as Dota positions.  Repair them
            # from the archived raw bootstrap regardless of age instead of refetching
            # a possibly-finished match from the live DLTV endpoint.  The bucket in
            # the dedupe key lets the repair retry on later cycles until the latest
            # draft for the map is no longer a legacy snapshot.
            if legacy_repairs_enqueued >= legacy_repair_cap:
                continue
            await jobs.enqueue(
                session,
                job_type=JobType.REPAIR_LEGACY_DRAFT,
                dedupe_key=f"repair-legacy-draft:{canonical_map.valve_match_id}:{bucket}",
                payload={"valve_match_id": canonical_map.valve_match_id},
                priority=20,
            )
            legacy_repairs_enqueued += 1
            continue
        await jobs.enqueue(
            session,
            job_type=JobType.BOOTSTRAP_DLTV_MATCH,
            dedupe_key=f"periodic-dltv-draft:{canonical_map.valve_match_id}:{bucket}",
            payload={"valve_match_id": canonical_map.valve_match_id},
            priority=25,
        )
        enqueued += 1
    return DraftRefreshResult(
        active_maps=len(active_map_ids),
        enqueued=enqueued,
        legacy_repairs_enqueued=legacy_repairs_enqueued,
    )
