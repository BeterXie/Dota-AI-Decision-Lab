import asyncio
from datetime import UTC, datetime, timedelta
from time import perf_counter
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import Base
from app.domain.events import DomainEvent, DomainEventType
from app.domain.jobs import DurableJob, JobStatus, JobType
from app.events.dispatcher import DomainEventDispatcher
from app.events.outbox import EventRepository
from app.jobs.reconciliation import ReconciliationService
from app.jobs.repository import JobRepository
from app.jobs.runner import JobRunner
from app.models import (
    CanonicalMap,
    CanonicalSeries,
    CanonicalTeam,
    DecisionSnapshotRecord,
    DltvLiveObservationRecord,
    DomainEventRecord,
    DurableJobRecord,
    HistoricalMapRecord,
    OddsObservationRecord,
    ProviderMatchMapping,
    ProviderRawEvent,
)
from app.snapshots.repository import SnapshotRepository


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
        EventRepository(),
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
async def test_reconciliation_rechecks_stale_live_map_in_time_buckets() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    jobs = JobRepository()
    now = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)

    async with factory() as session, session.begin():
        team_a = CanonicalTeam(name="Radiant")
        team_b = CanonicalTeam(name="Dire")
        session.add_all((team_a, team_b))
        await session.flush()
        series = CanonicalSeries(team_a_id=team_a.id, team_b_id=team_b.id)
        session.add(series)
        await session.flush()
        canonical_map = CanonicalMap(
            series_id=series.id,
            map_number=1,
            valve_match_id=8940000001,
        )
        session.add(canonical_map)
        await session.flush()
        session.add_all(
            (
                ProviderMatchMapping(
                    provider="raybet",
                    provider_match_id="38420001",
                    canonical_series_id=series.id,
                    resolved_by="PROVIDER_DISCOVERY",
                    confidence=1.0,
                ),
                DltvLiveObservationRecord(
                    canonical_map_id=canonical_map.id,
                    valve_match_id=8940000001,
                    game_time_seconds=2400,
                    radiant_kills=20,
                    dire_kills=15,
                    radiant_nw_lead=5000,
                    source_game_time=2400,
                    received_at=now - timedelta(minutes=4),
                    payload_hash="stale-live",
                    last_message_received_at=now - timedelta(minutes=4),
                    last_state_change_received_at=now - timedelta(minutes=4),
                    raw_event_id=uuid4(),
                ),
            )
        )
        map_id = canonical_map.id

    reconciliation = ReconciliationService(
        jobs,
        EventRepository(),
        lease_seconds=120,
        ai_experiments=(),
        future_odds_horizons=(),
    )
    async with factory() as session, session.begin():
        first = await reconciliation.run(session, now=now)
        assert first.postmatch_jobs == 1
    async with factory() as session, session.begin():
        duplicate = await reconciliation.run(session, now=now + timedelta(minutes=1))
        assert duplicate.postmatch_jobs == 0
    async with factory() as session, session.begin():
        next_bucket = await reconciliation.run(session, now=now + timedelta(minutes=16))
        assert next_bucket.postmatch_jobs == 1

    async with factory() as session:
        records = list(
            (
                await session.scalars(
                    select(DurableJobRecord).where(
                        DurableJobRecord.job_type == JobType.RESOLVE_POSTMATCH.value
                    )
                )
            ).all()
        )
        assert len(records) == 2
        assert all(record.dedupe_key.startswith("reconcile-postmatch-v2:") for record in records)
        assert all(record.payload["canonical_map_id"] == str(map_id) for record in records)
        assert all(record.payload["valve_match_id"] == 8940000001 for record in records)

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
        EventRepository(),
        lease_seconds=120,
        ai_experiments=(),
        future_odds_horizons=(30, 60),
    )
    async with factory() as session, session.begin():
        result = await reconciliation.run(session, now=now)
        assert result.settlement_jobs == 0

    await engine.dispose()


@pytest.mark.asyncio
async def test_reconciliation_only_enqueues_ai_after_ten_minutes() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    jobs = JobRepository()
    snapshots = SnapshotRepository()
    now = datetime(2026, 8, 12, tzinfo=UTC)

    async with factory() as session, session.begin():
        early = await snapshots.persist(
            session,
            canonical_map_id=None,
            decision_at=now,
            mode="LIVE_BASIC",
            identity={"team_a": {"name": "A"}, "team_b": {"name": "B"}},
            market={},
            draft=None,
            history={},
            live={"game_time_seconds": 599},
            quality={"eligible": True, "blockers": [], "warnings": []},
        )
        eligible = await snapshots.persist(
            session,
            canonical_map_id=None,
            decision_at=now + timedelta(seconds=1),
            mode="LIVE_BASIC",
            identity={"team_a": {"name": "A"}, "team_b": {"name": "B"}},
            market={},
            draft=None,
            history={},
            live={"game_time_seconds": 600},
            quality={"eligible": True, "blockers": [], "warnings": []},
        )

    reconciliation = ReconciliationService(
        jobs,
        EventRepository(),
        lease_seconds=120,
        ai_experiments=(("openai", "fixture-model", "prompt-v1", "policy-v1", "ai-view-v2"),),
        future_odds_horizons=(),
        ai_min_game_time_seconds=600,
    )
    for _ in range(2):
        async with factory() as session, session.begin():
            await reconciliation.run(session, now=now)

    async with factory() as session:
        records = list(
            (
                await session.scalars(
                    select(DurableJobRecord).where(
                        DurableJobRecord.job_type == JobType.RUN_AI_PROVIDER.value
                    )
                )
            ).all()
        )
        assert len(records) == 1
        assert records[0].payload == {
            "snapshot_id": str(eligible.snapshot_id),
            "provider": "openai",
            "model": "fixture-model",
        }
        assert records[0].payload["snapshot_id"] != str(early.snapshot_id)
        # Version-scoped dedupe so an ai-view bump always re-runs, and the
        # backfill yields to live event jobs.
        assert records[0].dedupe_key == (
            f"ai:{eligible.snapshot_hash}:openai:fixture-model:"
            "prompt-v1:policy-v1:ai-view-v2"
        )
        assert records[0].priority == 150
        assert await session.scalar(select(func.count()).select_from(DecisionSnapshotRecord)) == 2

    await engine.dispose()


@pytest.mark.asyncio
async def test_reconciliation_replays_processed_snapshot_trigger_without_snapshot() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    jobs = JobRepository()
    now = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)
    canonical_map_id = uuid4()

    async with factory() as session, session.begin():
        event = DomainEventRecord(
            event_type=DomainEventType.DECISION_CHECKPOINT_DUE.value,
            aggregate_type="canonical_map",
            aggregate_id=str(canonical_map_id),
            dedupe_key=f"checkpoint:{canonical_map_id}:10",
            payload={
                "canonical_map_id": str(canonical_map_id),
                "decision_at": now.isoformat(),
                "checkpoint_minute": 10,
            },
            occurred_at=now,
            processed_at=now,
        )
        session.add(event)
        team_a_id = uuid4()
        team_b_id = uuid4()
        session.add_all(
            [
                DltvLiveObservationRecord(
                    canonical_map_id=canonical_map_id,
                    valve_match_id=1,
                    game_time_seconds=600,
                    radiant_kills=1,
                    dire_kills=1,
                    radiant_nw_lead=0,
                    first_blood=None,
                    source_game_time=600,
                    received_at=now,
                    payload_hash="fixture-live",
                    last_message_received_at=now,
                    last_state_change_received_at=now,
                    raw_event_id=uuid4(),
                ),
                OddsObservationRecord(
                    provider_match_id=1,
                    odds_id=10,
                    canonical_map_id=canonical_map_id,
                    market_type="Winner",
                    match_stage="r1",
                    selection_team_id=team_a_id,
                    price=2.0,
                    implied_probability=0.5,
                    received_at=now,
                    raw_event_id=uuid4(),
                ),
                OddsObservationRecord(
                    provider_match_id=1,
                    odds_id=11,
                    canonical_map_id=canonical_map_id,
                    market_type="Winner",
                    match_stage="r1",
                    selection_team_id=team_b_id,
                    price=2.0,
                    implied_probability=0.5,
                    received_at=now,
                    raw_event_id=uuid4(),
                ),
            ]
        )
        await session.flush()
        event_id = event.id

    reconciliation = ReconciliationService(
        jobs,
        EventRepository(),
        lease_seconds=120,
        ai_experiments=(),
        future_odds_horizons=(),
    )
    async with factory() as session, session.begin():
        first = await reconciliation.run(session, now=now)
        assert first.snapshot_jobs == 1
    async with factory() as session, session.begin():
        second = await reconciliation.run(session, now=now)
        assert second.snapshot_jobs == 0

    async with factory() as session:
        record = await session.scalar(
            select(DurableJobRecord).where(
                DurableJobRecord.job_type == JobType.BUILD_SNAPSHOT.value,
                DurableJobRecord.dedupe_key == f"reconcile-snapshot-v2:{event_id}",
            )
        )
        assert record is not None
        assert record.payload == {
            "canonical_map_id": str(canonical_map_id),
            "canonical_series_id": None,
            "decision_at": now.isoformat(),
            "reconciliation_event_id": str(event_id),
        }

    await engine.dispose()


@pytest.mark.asyncio
async def test_reconciliation_replays_later_checkpoint_when_earlier_has_snapshot() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    jobs = JobRepository()
    now = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)
    later = now + timedelta(minutes=10)
    canonical_map_id = uuid4()

    async with factory() as session, session.begin():
        team_a_id = uuid4()
        team_b_id = uuid4()
        event_10 = DomainEventRecord(
            event_type=DomainEventType.DECISION_CHECKPOINT_DUE.value,
            aggregate_type="canonical_map",
            aggregate_id=str(canonical_map_id),
            dedupe_key=f"checkpoint:{canonical_map_id}:10",
            payload={
                "canonical_map_id": str(canonical_map_id),
                "decision_at": now.isoformat(),
                "checkpoint_minute": 10,
            },
            occurred_at=now,
            processed_at=now,
        )
        event_20 = DomainEventRecord(
            event_type=DomainEventType.DECISION_CHECKPOINT_DUE.value,
            aggregate_type="canonical_map",
            aggregate_id=str(canonical_map_id),
            dedupe_key=f"checkpoint:{canonical_map_id}:20",
            payload={
                "canonical_map_id": str(canonical_map_id),
                "decision_at": later.isoformat(),
                "checkpoint_minute": 20,
            },
            occurred_at=later,
            processed_at=later,
        )
        session.add_all((event_10, event_20))
        session.add(
            DecisionSnapshotRecord(
                id=uuid4(),
                canonical_map_id=canonical_map_id,
                decision_at=now,
                created_at=now,
                mode="LIVE_BASIC",
                canonical_payload={},
                snapshot_hash="fixture-snapshot-10",
            )
        )
        session.add_all(
            [
                DltvLiveObservationRecord(
                    canonical_map_id=canonical_map_id,
                    valve_match_id=1,
                    game_time_seconds=1200,
                    radiant_kills=1,
                    dire_kills=1,
                    radiant_nw_lead=0,
                    first_blood=None,
                    source_game_time=1200,
                    received_at=later,
                    payload_hash="fixture-live",
                    last_message_received_at=later,
                    last_state_change_received_at=later,
                    raw_event_id=uuid4(),
                ),
                OddsObservationRecord(
                    provider_match_id=1,
                    odds_id=10,
                    canonical_map_id=canonical_map_id,
                    market_type="Winner",
                    match_stage="r1",
                    selection_team_id=team_a_id,
                    price=2.0,
                    implied_probability=0.5,
                    received_at=now,
                    raw_event_id=uuid4(),
                ),
                OddsObservationRecord(
                    provider_match_id=1,
                    odds_id=11,
                    canonical_map_id=canonical_map_id,
                    market_type="Winner",
                    match_stage="r1",
                    selection_team_id=team_b_id,
                    price=2.0,
                    implied_probability=0.5,
                    received_at=now,
                    raw_event_id=uuid4(),
                ),
            ]
        )
        await session.flush()
        event_20_id = event_20.id

    reconciliation = ReconciliationService(
        jobs,
        EventRepository(),
        lease_seconds=120,
        ai_experiments=(),
        future_odds_horizons=(),
    )
    async with factory() as session, session.begin():
        first = await reconciliation.run(session, now=later)
        assert first.snapshot_jobs == 1
    async with factory() as session, session.begin():
        second = await reconciliation.run(session, now=later)
        assert second.snapshot_jobs == 0

    async with factory() as session:
        record = await session.scalar(
            select(DurableJobRecord).where(
                DurableJobRecord.job_type == JobType.BUILD_SNAPSHOT.value,
                DurableJobRecord.dedupe_key == f"reconcile-snapshot-v2:{event_20_id}",
            )
        )
        assert record is not None
        assert record.payload["decision_at"] == later.isoformat()

    await engine.dispose()


@pytest.mark.asyncio
async def test_job_runner_stops_touching_job_when_lease_is_lost() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    class LostLeaseRepository(JobRepository):
        def __init__(self) -> None:
            super().__init__()
            self.fail_calls: list[str] = []
            self.succeed_calls: list[object] = []

        async def renew_lease(self, session, *, job_id, worker_id, renewed_at=None) -> bool:
            return False

        async def fail(self, session, *, job_id, worker_id, error, failed_at=None):
            self.fail_calls.append(error)
            await super().fail(
                session, job_id=job_id, worker_id=worker_id, error=error, failed_at=failed_at
            )

        async def succeed(self, session, *, job_id, worker_id, completed_at=None):
            self.succeed_calls.append(job_id)
            await super().succeed(
                session, job_id=job_id, worker_id=worker_id, completed_at=completed_at
            )

    repository = LostLeaseRepository()
    now = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)
    async with factory() as session, session.begin():
        await repository.enqueue(
            session,
            job_type=JobType.BUILD_SNAPSHOT,
            dedupe_key="lease-lost-job",
            payload={"canonical_map_id": str(uuid4())},
            not_before=now,
        )
    async with factory() as session, session.begin():
        claimed = await repository.claim(session, worker_id="worker-1", now=now)
        job = claimed[0]
    assert job is not None

    progress: dict[str, bool] = {"finished": False}

    async def _slow_handler(_job: DurableJob) -> None:
        # Outlive the renewal interval (lease_seconds/3 -> min 1s) so the
        # renewal task actually attempts to renew and discovers the lost lease.
        await asyncio.sleep(1.2)
        progress["finished"] = True

    runner = JobRunner(
        worker_id="worker-1",
        session_factory=factory,
        repository=repository,
        handlers={JobType.BUILD_SNAPSHOT: _slow_handler},
        poll_seconds=1.0,
        lease_seconds=0.01,
    )
    started = perf_counter()
    await runner._execute(job)
    elapsed = perf_counter() - started

    assert repository.fail_calls == []
    assert repository.succeed_calls == []
    # The handler was cancelled as soon as the renewal failed, instead of
    # running to completion while another worker already reclaimed the job.
    assert progress["finished"] is False
    assert elapsed < 1.5
    async with factory() as session:
        record = await session.get(DurableJobRecord, job.id)
        # The job stays RUNNING: the losing worker must not mutate it; the
        # reclaiming reconciliation assigns it to the next worker.
        assert record is not None
        assert record.status == JobStatus.RUNNING.value
        assert record.locked_by == "worker-1"

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


@pytest.mark.asyncio
async def test_reconciliation_sweeps_missed_real_time_checkpoints() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    jobs = JobRepository()
    now = datetime(2026, 8, 12, 12, 20, 30, tzinfo=UTC)
    anchor_ts = int((now - timedelta(minutes=10, seconds=30)).timestamp())

    async with factory() as session, session.begin():
        team_a = CanonicalTeam(name="A")
        team_b = CanonicalTeam(name="B")
        session.add_all((team_a, team_b))
        await session.flush()
        series = CanonicalSeries(team_a_id=team_a.id, team_b_id=team_b.id)
        session.add(series)
        await session.flush()
        canonical_map = CanonicalMap(
            series_id=series.id,
            map_number=1,
            valve_match_id=8940000009,
        )
        session.add(canonical_map)
        await session.flush()
        map_id = canonical_map.id
        session.add_all(
            (
                ProviderRawEvent(
                    provider="dltv",
                    event_type="DLTV_BOOTSTRAP",
                    provider_key="8940000009",
                    payload={"is_picks_ended_time": anchor_ts},
                    received_at=now,
                    payload_hash="sweep-bootstrap",
                    parser_version="fixture",
                ),
                DltvLiveObservationRecord(
                    canonical_map_id=canonical_map.id,
                    valve_match_id=8940000009,
                    game_time_seconds=600,
                    radiant_kills=1,
                    dire_kills=1,
                    radiant_nw_lead=0,
                    source_game_time=600,
                    received_at=now - timedelta(seconds=60),
                    payload_hash="sweep-live",
                    last_message_received_at=now - timedelta(seconds=60),
                    last_state_change_received_at=now - timedelta(seconds=60),
                    raw_event_id=uuid4(),
                ),
            )
        )

    reconciliation = ReconciliationService(
        jobs,
        EventRepository(),
        lease_seconds=120,
        ai_experiments=(),
        future_odds_horizons=(),
    )
    async with factory() as session, session.begin():
        first = await reconciliation.run(session, now=now)
        assert first.checkpoint_sweep_jobs == 1
    async with factory() as session, session.begin():
        second = await reconciliation.run(session, now=now)
        assert second.checkpoint_sweep_jobs == 0

    async with factory() as session:
        events = list(
            (
                await session.scalars(
                    select(DomainEventRecord).where(
                        DomainEventRecord.event_type
                        == DomainEventType.DECISION_CHECKPOINT_DUE.value
                    )
                )
            ).all()
        )
        assert len(events) == 1
        assert events[0].payload["checkpoint_minute"] == 10
        assert events[0].payload["basis"] == "real_time"
        assert events[0].dedupe_key == f"checkpoint-real:{map_id}:10"

    await engine.dispose()


@pytest.mark.asyncio
async def test_reconciliation_sweep_skips_checkpoints_missed_beyond_grace() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime(2026, 8, 12, 12, 31, 0, tzinfo=UTC)
    anchor_ts = int((now - timedelta(minutes=31)).timestamp())

    async with factory() as session, session.begin():
        team_a = CanonicalTeam(name="A")
        team_b = CanonicalTeam(name="B")
        session.add_all((team_a, team_b))
        await session.flush()
        series = CanonicalSeries(team_a_id=team_a.id, team_b_id=team_b.id)
        session.add(series)
        await session.flush()
        canonical_map = CanonicalMap(
            series_id=series.id,
            map_number=1,
            valve_match_id=8940000010,
        )
        session.add(canonical_map)
        await session.flush()
        session.add_all(
            (
                ProviderRawEvent(
                    provider="dltv",
                    event_type="DLTV_BOOTSTRAP",
                    provider_key="8940000010",
                    payload={"is_picks_ended_time": anchor_ts},
                    received_at=now,
                    payload_hash="sweep-bootstrap",
                    parser_version="fixture",
                ),
                DltvLiveObservationRecord(
                    canonical_map_id=canonical_map.id,
                    valve_match_id=8940000010,
                    game_time_seconds=1860,
                    radiant_kills=1,
                    dire_kills=1,
                    radiant_nw_lead=0,
                    source_game_time=1860,
                    received_at=now - timedelta(seconds=30),
                    payload_hash="sweep-live",
                    last_message_received_at=now - timedelta(seconds=30),
                    last_state_change_received_at=now - timedelta(seconds=30),
                    raw_event_id=uuid4(),
                ),
            )
        )
        # Minute 10 was already recorded; minutes 15-25 were missed during a
        # long feed stall (>5 minutes past their crossing) and must NOT fire
        # retroactively. Minute 30 crossed 60s ago -> the sweep fires only it.
        await EventRepository().record(
            session,
            DomainEvent(
                event_type=DomainEventType.DECISION_CHECKPOINT_DUE,
                aggregate_type="canonical_map",
                aggregate_id=str(canonical_map.id),
                dedupe_key=f"checkpoint-real:{canonical_map.id}:10",
                payload={
                    "canonical_map_id": str(canonical_map.id),
                    "decision_at": (now - timedelta(minutes=21)).isoformat(),
                    "checkpoint_minute": 10,
                    "basis": "real_time",
                },
                occurred_at=now - timedelta(minutes=21),
            ),
        )

    reconciliation = ReconciliationService(
        JobRepository(),
        EventRepository(),
        lease_seconds=120,
        ai_experiments=(),
        future_odds_horizons=(),
    )
    async with factory() as session, session.begin():
        result = await reconciliation.run(session, now=now)
        assert result.checkpoint_sweep_jobs == 1

    async with factory() as session:
        events = list(
            (
                await session.scalars(
                    select(DomainEventRecord).where(
                        DomainEventRecord.event_type
                        == DomainEventType.DECISION_CHECKPOINT_DUE.value
                    )
                )
            ).all()
        )
        assert {event.payload["checkpoint_minute"] for event in events} == {10, 30}

    await engine.dispose()
