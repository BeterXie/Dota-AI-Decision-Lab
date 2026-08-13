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
        lease_seconds=120,
        ai_experiments=(("openai", "fixture-model", "prompt-v1", "policy-v1"),),
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
        assert records[0].payload["snapshot_id"] == str(eligible.snapshot_id)
        assert records[0].payload["snapshot_id"] != str(early.snapshot_id)
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
