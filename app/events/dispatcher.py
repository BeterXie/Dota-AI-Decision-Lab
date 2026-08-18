from collections import defaultdict
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import load_only

from app.ai.jobs import ai_job_dedupe_key_for_experiment, ai_job_payload, ai_job_priority
from app.domain.events import DomainEventType
from app.domain.jobs import JobType
from app.jobs.repository import JobRepository
from app.models import DecisionSnapshotRecord, DomainEventRecord, OutboxEventRecord
from app.runtime_config import active_ai_experiments

EVENT_JOB_MAP: dict[DomainEventType, JobType] = {
    DomainEventType.MARKET_DISCOVERED: JobType.REFRESH_ODDS_REGISTRY,
    DomainEventType.ODDS_REGISTRY_REFRESH_REQUIRED: JobType.REFRESH_ODDS_REGISTRY,
    DomainEventType.DLTV_MATCH_DISCOVERED: JobType.BOOTSTRAP_DLTV_MATCH,
    DomainEventType.DLTV_MATCH_RESOLVED: JobType.SYNC_HISTORICAL,
    DomainEventType.DRAFT_CONFIRMED: JobType.BUILD_DRAFT_CURVE,
    DomainEventType.MAP_STARTED: JobType.SYNC_HISTORICAL,
    DomainEventType.DECISION_CHECKPOINT_DUE: JobType.BUILD_SNAPSHOT,
    DomainEventType.SIGNIFICANT_ODDS_MOVE: JobType.BUILD_SNAPSHOT,
    DomainEventType.MARKET_REOPENED: JobType.BUILD_SNAPSHOT,
    DomainEventType.MAP_ENDED: JobType.RESOLVE_POSTMATCH,
    DomainEventType.BASIC_RESULT_READY: JobType.SETTLE_MAP,
    DomainEventType.ADVANCED_RESULT_READY: JobType.SYNC_HISTORICAL,
    DomainEventType.SNAPSHOT_BUILD_REQUESTED: JobType.BUILD_SNAPSHOT,
    DomainEventType.AI_DECISION_REQUESTED: JobType.RUN_AI_PROVIDER,
    DomainEventType.FUTURE_ODDS_CAPTURE_DUE: JobType.CAPTURE_FUTURE_ODDS,
    DomainEventType.SETTLEMENT_REQUIRED: JobType.SETTLE_MAP,
    DomainEventType.EVALUATION_REQUIRED: JobType.EVALUATE_DECISION,
}

EVENT_ADDITIONAL_JOBS: dict[DomainEventType, tuple[JobType, ...]] = {
    DomainEventType.MARKET_DISCOVERED: (JobType.SYNC_HISTORICAL,),
    DomainEventType.DRAFT_CONFIRMED: (JobType.SYNC_HISTORICAL,),
}


def utc_now() -> datetime:
    return datetime.now(UTC)


class DomainEventDispatcher:
    def __init__(
        self,
        jobs: JobRepository,
        ai_experiments: tuple[tuple[str, str, str, str, str], ...] = (),
    ) -> None:
        self._jobs = jobs
        self._ai_experiments = ai_experiments

    async def dispatch_pending(self, session: AsyncSession, *, limit: int = 100) -> int:
        records = list(
            (
                await session.scalars(
                    select(DomainEventRecord)
                    .where(DomainEventRecord.processed_at.is_(None))
                    .order_by(DomainEventRecord.occurred_at)
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            ).all()
        )
        typed_records = [(record, DomainEventType(record.event_type)) for record in records]
        ai_snapshot_ids = {
            snapshot_id
            for record, event_type in typed_records
            if event_type is DomainEventType.AI_DECISION_REQUESTED
            and (snapshot_id := _payload_uuid(record.payload, "snapshot_id")) is not None
        }
        ended_map_ids = {
            canonical_map_id
            for record, event_type in typed_records
            if event_type is DomainEventType.MAP_ENDED
            and (canonical_map_id := _payload_uuid(record.payload, "canonical_map_id")) is not None
        }
        snapshots = (
            list(
                (
                    await session.scalars(
                        select(DecisionSnapshotRecord)
                        .options(
                            load_only(
                                DecisionSnapshotRecord.id,
                                DecisionSnapshotRecord.canonical_map_id,
                                DecisionSnapshotRecord.mode,
                                DecisionSnapshotRecord.snapshot_hash,
                            )
                        )
                        .where(
                            or_(
                                DecisionSnapshotRecord.id.in_(ai_snapshot_ids),
                                DecisionSnapshotRecord.canonical_map_id.in_(ended_map_ids),
                            )
                        )
                    )
                ).all()
            )
            if ai_snapshot_ids or ended_map_ids
            else []
        )
        snapshot_by_id = {snapshot.id: snapshot for snapshot in snapshots}
        snapshot_ids_by_map: dict[UUID, list[UUID]] = defaultdict(list)
        for snapshot in snapshots:
            if snapshot.canonical_map_id is not None:
                snapshot_ids_by_map[snapshot.canonical_map_id].append(snapshot.id)

        for record, event_type in typed_records:
            if event_type is DomainEventType.AI_DECISION_REQUESTED:
                snapshot_id = _payload_uuid(record.payload, "snapshot_id")
                await self._enqueue_ai_provider_jobs(
                    session,
                    snapshot=snapshot_by_id.get(snapshot_id),
                )
            else:
                job_type = EVENT_JOB_MAP[event_type]
                await self._jobs.enqueue(
                    session,
                    job_type=job_type,
                    dedupe_key=f"event:{record.id}",
                    payload={**record.payload, "domain_event_id": str(record.id)},
                    priority=100,
                )
            for additional_job_type in EVENT_ADDITIONAL_JOBS.get(event_type, ()):
                await self._jobs.enqueue(
                    session,
                    job_type=additional_job_type,
                    dedupe_key=f"event:{record.id}:{additional_job_type.value}",
                    payload={**record.payload, "domain_event_id": str(record.id)},
                )
            if event_type is DomainEventType.MAP_ENDED:
                canonical_map_id = _payload_uuid(record.payload, "canonical_map_id")
                await self._enqueue_closing_captures(
                    session,
                    record,
                    snapshot_ids=snapshot_ids_by_map.get(canonical_map_id, ()),
                )
            record.processed_at = utc_now()
        return len(records)

    async def _enqueue_ai_provider_jobs(
        self,
        session: AsyncSession,
        *,
        snapshot: DecisionSnapshotRecord | None,
    ) -> None:
        """Fan out using the provider set active at scheduling time."""
        if snapshot is None:
            return
        priority = ai_job_priority(snapshot.mode)
        experiments = await active_ai_experiments(session, self._ai_experiments)
        for experiment in experiments:
            await self._jobs.enqueue(
                session,
                job_type=JobType.RUN_AI_PROVIDER,
                dedupe_key=ai_job_dedupe_key_for_experiment(snapshot.snapshot_hash, experiment),
                payload=ai_job_payload(snapshot.id, experiment[0], experiment[1]),
                priority=priority,
            )

    async def _enqueue_closing_captures(
        self,
        session: AsyncSession,
        record: DomainEventRecord,
        *,
        snapshot_ids: tuple[UUID, ...] | list[UUID],
    ) -> None:
        for snapshot_id in snapshot_ids:
            await self._jobs.enqueue(
                session,
                job_type=JobType.CAPTURE_FUTURE_ODDS,
                dedupe_key=f"closing-odds:{snapshot_id}",
                payload={
                    "snapshot_id": str(snapshot_id),
                    "capture_type": "CLOSING",
                    "triggered_at": record.occurred_at.isoformat(),
                },
                not_before=record.occurred_at,
            )


def _payload_uuid(payload: dict, field: str) -> UUID | None:
    value = payload.get(field)
    if not isinstance(value, str):
        return None
    try:
        return UUID(value)
    except ValueError:
        return None


class OutboxDispatcher:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        publish: Callable[[str, dict], Awaitable[None]],
    ) -> None:
        self._session_factory = session_factory
        self._publish = publish

    async def dispatch_once(self, *, limit: int = 100) -> int:
        async with self._session_factory() as session, session.begin():
            records = list(
                (
                    await session.scalars(
                        select(OutboxEventRecord)
                        .where(OutboxEventRecord.published_at.is_(None))
                        .order_by(OutboxEventRecord.created_at)
                        .limit(limit)
                        .with_for_update(skip_locked=True)
                    )
                ).all()
            )
            published = 0
            for record in records:
                record.attempt_count += 1
                try:
                    await self._publish(record.topic, record.payload)
                except Exception as exc:
                    record.last_error = f"{type(exc).__name__}: {exc}"
                    continue
                record.published_at = utc_now()
                record.last_error = None
                published += 1
            return published
