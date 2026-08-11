from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.events import DomainEventType
from app.domain.jobs import JobType
from app.jobs.repository import JobRepository
from app.models import DomainEventRecord, OutboxEventRecord

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


def utc_now() -> datetime:
    return datetime.now(UTC)


class DomainEventDispatcher:
    def __init__(self, jobs: JobRepository) -> None:
        self._jobs = jobs

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
        for record in records:
            event_type = DomainEventType(record.event_type)
            job_type = EVENT_JOB_MAP[event_type]
            await self._jobs.enqueue(
                session,
                job_type=job_type,
                dedupe_key=f"event:{record.id}",
                payload={**record.payload, "domain_event_id": str(record.id)},
            )
            record.processed_at = utc_now()
        return len(records)


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
