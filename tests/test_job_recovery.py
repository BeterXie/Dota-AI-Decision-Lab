from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import Base
from app.domain.jobs import JobStatus, JobType
from app.jobs.reconciliation import ReconciliationService
from app.jobs.repository import JobRepository
from app.models import DurableJobRecord, HistoricalMapRecord


@pytest.mark.asyncio
async def test_job_claim_filter_and_expired_lease_recovery() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    jobs = JobRepository()
    now = datetime(2026, 8, 12, tzinfo=UTC)

    async with factory() as session, session.begin():
        await jobs.enqueue(
            session,
            job_type=JobType.BUILD_SNAPSHOT,
            dedupe_key="snapshot-1",
            payload={"canonical_map_id": str(uuid4())},
            not_before=now,
        )
        await jobs.enqueue(
            session,
            job_type=JobType.SETTLE_MAP,
            dedupe_key="settlement-1",
            payload={"canonical_map_id": str(uuid4())},
            not_before=now,
        )

    async with factory() as session, session.begin():
        claimed = await jobs.claim(
            session,
            worker_id="snapshot-worker",
            now=now,
            job_types=(JobType.BUILD_SNAPSHOT,),
        )
        assert [job.job_type for job in claimed] == [JobType.BUILD_SNAPSHOT]

    async with factory() as session, session.begin():
        reclaimed = await jobs.reclaim_expired(
            session,
            lease_seconds=30,
            now=now + timedelta(seconds=31),
        )
        assert reclaimed == 1

    async with factory() as session:
        recovered = await session.scalar(
            select(DurableJobRecord).where(
                DurableJobRecord.job_type == JobType.BUILD_SNAPSHOT.value
            )
        )
        untouched = await session.scalar(
            select(DurableJobRecord).where(DurableJobRecord.job_type == JobType.SETTLE_MAP.value)
        )
        assert recovered is not None and recovered.status == JobStatus.RETRY_WAIT.value
        assert recovered.locked_by is None
        assert untouched is not None and untouched.status == JobStatus.PENDING.value

    await engine.dispose()


@pytest.mark.asyncio
async def test_reconciliation_enqueues_missing_settlement_idempotently() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    jobs = JobRepository()
    canonical_map_id = uuid4()
    now = datetime(2026, 8, 12, tzinfo=UTC)

    async with factory() as session, session.begin():
        session.add(
            HistoricalMapRecord(
                canonical_map_id=canonical_map_id,
                provider="opendota",
                provider_match_id="8940730389",
                started_at=now - timedelta(hours=1),
                winner_team_id=uuid4(),
                first_usable_at=now,
                sync_status="BASIC_READY",
                raw_event_id=uuid4(),
            )
        )

    reconciliation = ReconciliationService(
        jobs,
        lease_seconds=120,
        ai_experiments=(),
        future_odds_horizons=(30, 60),
    )
    for _ in range(2):
        async with factory() as session, session.begin():
            await reconciliation.run(session, now=now)

    async with factory() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(DurableJobRecord)
            .where(DurableJobRecord.job_type == JobType.SETTLE_MAP.value)
        )
        assert count == 1

    await engine.dispose()
