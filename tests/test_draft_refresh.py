from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import Base
from app.domain.jobs import JobType
from app.draft.refresh import schedule_incomplete_draft_refreshes
from app.jobs.repository import JobRepository
from app.models import (
    CanonicalMap,
    CanonicalSeries,
    CanonicalTeam,
    DltvLiveObservationRecord,
    DraftSnapshotRecord,
    DurableJobRecord,
)


@pytest.mark.asyncio
async def test_draft_refresh_only_enqueues_active_incomplete_maps() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)
    async with factory() as session, session.begin():
        team_a = CanonicalTeam(name="A")
        team_b = CanonicalTeam(name="B")
        session.add_all((team_a, team_b))
        await session.flush()
        series = CanonicalSeries(team_a_id=team_a.id, team_b_id=team_b.id)
        session.add(series)
        await session.flush()
        incomplete = CanonicalMap(series_id=series.id, valve_match_id=1001)
        complete = CanonicalMap(series_id=series.id, valve_match_id=1002, map_number=2)
        stale = CanonicalMap(series_id=series.id, valve_match_id=1003, map_number=3)
        session.add_all((incomplete, complete, stale))
        await session.flush()
        session.add_all(
            (
                _live(incomplete.id, 1001, now),
                _live(complete.id, 1002, now),
                _live(stale.id, 1003, now - timedelta(minutes=20)),
                DraftSnapshotRecord(
                    canonical_map_id=complete.id,
                    valve_match_id=1002,
                    complete=True,
                    blockers=[],
                    warnings=[],
                    payload_hash="complete",
                    statistics_cutoff=now,
                    observed_at=now,
                    raw_event_id=incomplete.id,
                ),
            )
        )

    async with factory() as session, session.begin():
        result = await schedule_incomplete_draft_refreshes(
            session,
            JobRepository(),
            interval_seconds=30,
            now=now,
        )

    async with factory() as session:
        jobs = list((await session.scalars(select(DurableJobRecord))).all())
        count = await session.scalar(select(func.count()).select_from(DurableJobRecord))

    assert result.active_maps == 2
    assert result.enqueued == 1
    assert count == 1
    assert jobs[0].job_type == JobType.BOOTSTRAP_DLTV_MATCH.value
    assert jobs[0].payload == {"valve_match_id": 1001}
    await engine.dispose()


@pytest.mark.asyncio
async def test_draft_refresh_recovers_recent_incomplete_map_without_fresh_socket_state() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)
    async with factory() as session, session.begin():
        team_a = CanonicalTeam(name="A")
        team_b = CanonicalTeam(name="B")
        session.add_all((team_a, team_b))
        await session.flush()
        series = CanonicalSeries(team_a_id=team_a.id, team_b_id=team_b.id)
        session.add(series)
        await session.flush()
        canonical_map = CanonicalMap(series_id=series.id, valve_match_id=8941656460)
        session.add(canonical_map)
        await session.flush()
        session.add(
            DraftSnapshotRecord(
                canonical_map_id=canonical_map.id,
                valve_match_id=8941656460,
                complete=False,
                blockers=["DRAFT_PARTIAL"],
                warnings=[],
                payload_hash="incomplete",
                statistics_cutoff=now - timedelta(hours=2),
                observed_at=now - timedelta(hours=2),
                raw_event_id=canonical_map.id,
            )
        )

    async with factory() as session, session.begin():
        result = await schedule_incomplete_draft_refreshes(
            session,
            JobRepository(),
            interval_seconds=30,
            now=now,
        )

    assert result.active_maps == 0
    assert result.enqueued == 1
    await engine.dispose()


def _live(map_id, valve_match_id: int, received_at: datetime) -> DltvLiveObservationRecord:
    return DltvLiveObservationRecord(
        canonical_map_id=map_id,
        valve_match_id=valve_match_id,
        received_at=received_at,
        payload_hash=f"live-{valve_match_id}",
        reconnect_generation=0,
        last_message_received_at=received_at,
        last_state_change_received_at=received_at,
        raw_event_id=map_id,
    )
