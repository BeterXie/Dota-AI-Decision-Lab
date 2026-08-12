from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import Base
from app.domain.events import DomainEventType
from app.domain.jobs import JobStatus, JobType
from app.events.dispatcher import DomainEventDispatcher
from app.jobs.reconciliation import ReconciliationService
from app.jobs.repository import JobRepository
from app.models import (
    DomainEventRecord,
    DurableJobRecord,
    HistoricalMapRecord,
    ProviderMatchMapping,
)


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
    now = datetime(2026, 8, 12, tzinfo=UTC)

    async with factory() as session, session.begin():
        canonical_map_id = uuid4()
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
        session.add(
            ProviderMatchMapping(
                provider="raybet",
                provider_match_id="38423260",
                canonical_map_id=canonical_map_id,
                resolved_by="VALVE_MATCH_ID",
                confidence=1.0,
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


@pytest.mark.asyncio
async def test_reconciliation_ignores_historical_only_maps_for_settlement() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    jobs = JobRepository()
    now = datetime(2026, 8, 12, tzinfo=UTC)

    async with factory() as session, session.begin():
        session.add(
            HistoricalMapRecord(
                canonical_map_id=uuid4(),
                provider="stratz",
                provider_match_id="8936072794",
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
    async with factory() as session, session.begin():
        result = await reconciliation.run(session, now=now)
        assert result.settlement_jobs == 0

    await engine.dispose()


@pytest.mark.asyncio
async def test_market_discovery_dispatches_odds_and_historical_jobs() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime(2026, 8, 12, tzinfo=UTC)

    async with factory() as session, session.begin():
        session.add(
            DomainEventRecord(
                event_type=DomainEventType.MARKET_DISCOVERED.value,
                aggregate_type="raybet_match",
                aggregate_id="38424223",
                dedupe_key="raybet-match:38424223",
                payload={"provider_match_id": 38424223},
                occurred_at=now,
            )
        )

    async with factory() as session, session.begin():
        assert await DomainEventDispatcher(JobRepository()).dispatch_pending(session) == 1

    async with factory() as session:
        records = list(
            (
                await session.scalars(select(DurableJobRecord).order_by(DurableJobRecord.job_type))
            ).all()
        )
        assert {record.job_type for record in records} == {
            JobType.REFRESH_ODDS_REGISTRY.value,
            JobType.SYNC_HISTORICAL.value,
        }
        assert all(record.payload["provider_match_id"] == 38424223 for record in records)

    await engine.dispose()
