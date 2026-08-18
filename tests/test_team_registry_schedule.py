from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import Base
from app.domain.jobs import JobType
from app.identity.team_registry_schedule import (
    schedule_discovered_event_team_registry_refreshes,
    schedule_prestart_event_team_registry_refreshes,
)
from app.jobs.repository import JobRepository
from app.models import (
    CanonicalEvent,
    CanonicalSeries,
    CanonicalTeam,
    DurableJobRecord,
    ProviderEventMapping,
)


@pytest.mark.asyncio
async def test_registry_refresh_runs_on_discovery_then_each_24h_before_event_start() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    discovered_at = datetime(2026, 8, 18, 3, 0, tzinfo=UTC)

    async with factory.begin() as session:
        team_a = CanonicalTeam(name="Team A")
        team_b = CanonicalTeam(name="Team B")
        event = CanonicalEvent(name="Future Event", created_at=discovered_at)
        session.add_all((team_a, team_b, event))
        await session.flush()
        session.add_all(
            (
                ProviderEventMapping(
                    provider="raybet",
                    provider_event_id="9001",
                    canonical_event_id=event.id,
                ),
                CanonicalSeries(
                    event_id=event.id,
                    team_a_id=team_a.id,
                    team_b_id=team_b.id,
                    scheduled_at=discovered_at + timedelta(days=4),
                ),
            )
        )

    jobs = JobRepository()
    async with factory.begin() as session:
        first = await schedule_discovered_event_team_registry_refreshes(
            session,
            jobs,
            discovered_after=discovered_at - timedelta(seconds=1),
            now=discovered_at,
        )
        repeated = await schedule_discovered_event_team_registry_refreshes(
            session,
            jobs,
            discovered_after=discovered_at - timedelta(seconds=1),
            now=discovered_at + timedelta(minutes=1),
        )

    assert first.jobs_enqueued == 1
    assert repeated.jobs_enqueued == 1
    async with factory() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(DurableJobRecord)
            .where(DurableJobRecord.job_type == JobType.SYNC_TEAM_REGISTRY.value)
        )
        discovery_job = await session.scalar(
            select(DurableJobRecord).where(
                DurableJobRecord.job_type == JobType.SYNC_TEAM_REGISTRY.value
            )
        )
    assert count == 1
    assert discovery_job is not None
    assert discovery_job.payload["refresh_cycle"] == "discovered"
    assert set(discovery_job.payload["canonical_team_ids"]) == {str(team_a.id), str(team_b.id)}

    exact_24h = discovered_at + timedelta(hours=24)
    async with factory.begin() as session:
        discovery_at_boundary = await schedule_discovered_event_team_registry_refreshes(
            session,
            jobs,
            discovered_after=exact_24h - timedelta(hours=24),
            now=exact_24h,
        )
        first_periodic = await schedule_prestart_event_team_registry_refreshes(
            session,
            jobs,
            refresh_seconds=86_400,
            now=exact_24h,
        )
        repeated_periodic = await schedule_prestart_event_team_registry_refreshes(
            session,
            jobs,
            refresh_seconds=86_400,
            now=exact_24h + timedelta(minutes=30),
        )

    assert discovery_at_boundary.jobs_enqueued == 0
    assert first_periodic.jobs_enqueued == 1
    assert repeated_periodic.jobs_enqueued == 1
    async with factory() as session:
        rows = list(
            (
                await session.scalars(
                    select(DurableJobRecord)
                    .where(DurableJobRecord.job_type == JobType.SYNC_TEAM_REGISTRY.value)
                    .order_by(DurableJobRecord.created_at)
                )
            ).all()
        )
    assert len(rows) == 2
    assert rows[-1].payload["refresh_cycle"] == "prestart-1"

    async with factory.begin() as session:
        stopped = await schedule_prestart_event_team_registry_refreshes(
            session,
            jobs,
            refresh_seconds=86_400,
            now=discovered_at + timedelta(days=4, minutes=1),
        )
    assert stopped.jobs_enqueued == 0

    async with factory() as session:
        final_count = await session.scalar(
            select(func.count())
            .select_from(DurableJobRecord)
            .where(DurableJobRecord.job_type == JobType.SYNC_TEAM_REGISTRY.value)
        )
    assert final_count == 2
    await engine.dispose()


@pytest.mark.asyncio
async def test_prestart_refresh_ignores_non_raybet_events() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime(2026, 8, 18, 3, 0, tzinfo=UTC)

    async with factory.begin() as session:
        team_a = CanonicalTeam(name="Team A")
        team_b = CanonicalTeam(name="Team B")
        event = CanonicalEvent(name="Other Provider", created_at=now - timedelta(days=2))
        session.add_all((team_a, team_b, event))
        await session.flush()
        session.add(
            CanonicalSeries(
                event_id=event.id,
                team_a_id=team_a.id,
                team_b_id=team_b.id,
                scheduled_at=now + timedelta(days=2),
            )
        )

    async with factory.begin() as session:
        result = await schedule_prestart_event_team_registry_refreshes(
            session,
            JobRepository(),
            now=now,
        )
    assert result.events_considered == 0
    assert result.jobs_enqueued == 0
    await engine.dispose()
