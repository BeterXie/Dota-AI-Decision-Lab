from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.jobs import DurableJob, JobStatus, JobType
from app.models import DurableJobRecord, JobAttemptRecord


def utc_now() -> datetime:
    return datetime.now(UTC)


class JobRepository:
    async def enqueue(
        self,
        session: AsyncSession,
        *,
        job_type: JobType,
        dedupe_key: str,
        payload: dict[str, Any],
        priority: int = 100,
        not_before: datetime | None = None,
        max_attempts: int = 8,
    ) -> UUID:
        due = not_before or utc_now()
        dialect = session.get_bind().dialect.name
        if dialect == "postgresql":
            statement = (
                pg_insert(DurableJobRecord)
                .values(
                    job_type=job_type.value,
                    dedupe_key=dedupe_key,
                    payload=payload,
                    status=JobStatus.PENDING.value,
                    priority=priority,
                    not_before=due,
                    max_attempts=max_attempts,
                )
                .on_conflict_do_nothing(index_elements=["job_type", "dedupe_key"])
                .returning(DurableJobRecord.id)
            )
            created_id = await session.scalar(statement)
            if created_id is not None:
                return created_id

        existing_id = await session.scalar(
            select(DurableJobRecord.id).where(
                DurableJobRecord.job_type == job_type.value,
                DurableJobRecord.dedupe_key == dedupe_key,
            )
        )
        if existing_id is not None:
            return existing_id

        record = DurableJobRecord(
            job_type=job_type.value,
            dedupe_key=dedupe_key,
            payload=payload,
            status=JobStatus.PENDING.value,
            priority=priority,
            not_before=due,
            max_attempts=max_attempts,
        )
        session.add(record)
        await session.flush()
        return record.id

    async def claim(
        self,
        session: AsyncSession,
        *,
        worker_id: str,
        limit: int = 1,
        now: datetime | None = None,
        job_types: tuple[JobType, ...] | None = None,
    ) -> list[DurableJob]:
        claim_at = now or utc_now()
        statement = (
            select(DurableJobRecord)
            .where(
                DurableJobRecord.status.in_([JobStatus.PENDING.value, JobStatus.RETRY_WAIT.value]),
                DurableJobRecord.not_before <= claim_at,
            )
            .order_by(DurableJobRecord.priority, DurableJobRecord.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        if job_types:
            statement = statement.where(
                DurableJobRecord.job_type.in_([job_type.value for job_type in job_types])
            )
        records = list((await session.scalars(statement)).all())
        jobs: list[DurableJob] = []
        for record in records:
            record.status = JobStatus.RUNNING.value
            record.locked_by = worker_id
            record.locked_at = claim_at
            record.attempt_count += 1
            session.add(
                JobAttemptRecord(
                    job_id=record.id,
                    attempt_number=record.attempt_count,
                    worker_id=worker_id,
                    status=JobStatus.RUNNING.value,
                    started_at=claim_at,
                )
            )
            jobs.append(self._to_domain(record))
        await session.flush()
        return jobs

    async def succeed(
        self,
        session: AsyncSession,
        *,
        job_id: UUID,
        worker_id: str,
        completed_at: datetime | None = None,
    ) -> None:
        finished = completed_at or utc_now()
        job = await self._owned_job(session, job_id, worker_id)
        job.status = JobStatus.SUCCEEDED.value
        job.completed_at = finished
        job.locked_by = None
        job.locked_at = None
        attempt = await self._current_attempt(session, job)
        attempt.status = JobStatus.SUCCEEDED.value
        attempt.completed_at = finished

    async def fail(
        self,
        session: AsyncSession,
        *,
        job_id: UUID,
        worker_id: str,
        error: str,
        failed_at: datetime | None = None,
    ) -> JobStatus:
        now = failed_at or utc_now()
        job = await self._owned_job(session, job_id, worker_id)
        terminal = job.attempt_count >= job.max_attempts
        next_status = JobStatus.FAILED_TERMINAL if terminal else JobStatus.RETRY_WAIT
        job.status = next_status.value
        job.last_error = error
        job.locked_by = None
        job.locked_at = None
        if terminal:
            job.completed_at = now
        else:
            delay = min(2 ** max(job.attempt_count - 1, 0), 300)
            job.not_before = now + timedelta(seconds=delay)
        attempt = await self._current_attempt(session, job)
        attempt.status = next_status.value
        attempt.completed_at = now
        attempt.error = error
        return next_status

    async def renew_lease(
        self,
        session: AsyncSession,
        *,
        job_id: UUID,
        worker_id: str,
        renewed_at: datetime | None = None,
    ) -> bool:
        result = await session.execute(
            update(DurableJobRecord)
            .where(
                DurableJobRecord.id == job_id,
                DurableJobRecord.status == JobStatus.RUNNING.value,
                DurableJobRecord.locked_by == worker_id,
            )
            .values(locked_at=renewed_at or utc_now())
        )
        return bool(result.rowcount)

    async def reclaim_expired(
        self,
        session: AsyncSession,
        *,
        lease_seconds: float,
        now: datetime | None = None,
    ) -> int:
        current = now or utc_now()
        cutoff = current - timedelta(seconds=lease_seconds)
        records = list(
            (
                await session.scalars(
                    select(DurableJobRecord)
                    .where(
                        DurableJobRecord.status == JobStatus.RUNNING.value,
                        DurableJobRecord.locked_at < cutoff,
                    )
                    .with_for_update(skip_locked=True)
                )
            ).all()
        )
        for job in records:
            job.status = JobStatus.RETRY_WAIT.value
            job.not_before = current
            job.locked_by = None
            job.locked_at = None
            job.last_error = "worker lease expired"
            attempt = await self._current_attempt(session, job)
            attempt.status = JobStatus.RETRY_WAIT.value
            attempt.completed_at = current
            attempt.error = "worker lease expired"
        return len(records)

    async def counts_by_status(self, session: AsyncSession) -> dict[str, int]:
        rows: Sequence[tuple[str, int]] = (
            await session.execute(
                select(DurableJobRecord.status, func.count())
                .group_by(DurableJobRecord.status)
                .order_by(DurableJobRecord.status)
            )
        ).all()
        return {status: count for status, count in rows}

    async def _owned_job(
        self, session: AsyncSession, job_id: UUID, worker_id: str
    ) -> DurableJobRecord:
        job = await session.scalar(
            select(DurableJobRecord)
            .where(
                DurableJobRecord.id == job_id,
                DurableJobRecord.status == JobStatus.RUNNING.value,
                DurableJobRecord.locked_by == worker_id,
            )
            .with_for_update()
        )
        if job is None:
            raise ValueError("job is not owned by this worker")
        return job

    async def _current_attempt(
        self, session: AsyncSession, job: DurableJobRecord
    ) -> JobAttemptRecord:
        attempt = await session.scalar(
            select(JobAttemptRecord).where(
                JobAttemptRecord.job_id == job.id,
                JobAttemptRecord.attempt_number == job.attempt_count,
            )
        )
        if attempt is None:
            raise ValueError("job attempt record is missing")
        return attempt

    @staticmethod
    def _to_domain(record: DurableJobRecord) -> DurableJob:
        return DurableJob(
            id=record.id,
            job_type=JobType(record.job_type),
            dedupe_key=record.dedupe_key,
            payload=record.payload,
            status=JobStatus(record.status),
            priority=record.priority,
            not_before=record.not_before,
            created_at=record.created_at,
            attempt_count=record.attempt_count,
            max_attempts=record.max_attempts,
            locked_by=record.locked_by,
            locked_at=record.locked_at,
        )
