import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.ai.base import (
    AI_VIEW_VERSION,
    DECISION_POLICY_VERSION,
    PROMPT_VERSION,
    AiProviderResponse,
)
from app.ai.coordinator import AiCoordinator
from app.ai.jobs import ai_job_priority
from app.db import Base
from app.domain.decision import AiDecision
from app.domain.events import DomainEventType
from app.domain.jobs import DurableJob, JobStatus, JobType
from app.events.dispatcher import DomainEventDispatcher
from app.events.outbox import EventRepository
from app.jobs.handlers import ApplicationJobHandlers
from app.jobs.reconciliation import ReconciliationService
from app.jobs.repository import JobRepository
from app.models import (
    AiDecisionRecord,
    DomainEventRecord,
    DurableJobRecord,
)
from app.runtime.health import HealthRegistry
from app.snapshots.repository import SnapshotRepository


def _decision() -> AiDecision:
    return AiDecision(
        action="NO_BUY",
        fair_probability_a=None,
        confidence=0.5,
        market_assessment="UNKNOWN",
        minimum_acceptable_odds_a=None,
        primary_reasons=["No verified edge"],
        counter_arguments=[],
        data_quality_concerns=[],
        blockers=[],
    )


class EventedProvider:
    def __init__(self, name: str, *, delay: float = 0.0) -> None:
        self.name = name
        self.model = f"fixture-{name}"
        self.delay = delay
        self.started = asyncio.Event()
        self.finished = asyncio.Event()
        self.inputs: list[str] = []

    async def decide(self, snapshot_input: str) -> AiProviderResponse:
        self.inputs.append(snapshot_input)
        self.started.set()
        if self.delay:
            await asyncio.sleep(self.delay)
        self.finished.set()
        return AiProviderResponse(
            raw_response={"provider": self.name},
            decision=_decision(),
            model_version=self.model,
        )

    async def close(self) -> None:
        return None


async def _snapshot(session, *, mode: str = "LIVE_BASIC"):
    return await SnapshotRepository().persist(
        session,
        canonical_map_id=None,
        decision_at=datetime(2026, 8, 15, 12, 0, tzinfo=UTC),
        mode=mode,
        identity={
            "team_a": {"id": "team-a", "name": "A"},
            "team_b": {"id": "team-b", "name": "B"},
        },
        market={},
        draft=None,
        history={},
        live={"game_time_seconds": 600},
        quality={"eligible": True, "blockers": [], "warnings": []},
    )


@pytest.mark.asyncio
async def test_ai_event_fans_out_to_one_durable_job_per_experiment() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)
    async with factory() as session, session.begin():
        snapshot = await _snapshot(session, mode="PREMATCH")
        session.add(
            DomainEventRecord(
                event_type=DomainEventType.AI_DECISION_REQUESTED.value,
                aggregate_type="decision_snapshot",
                aggregate_id=str(snapshot.snapshot_id),
                dedupe_key=f"ai:{snapshot.snapshot_hash}",
                payload={"snapshot_id": str(snapshot.snapshot_id)},
                occurred_at=now,
            )
        )
        await session.flush()
        event_id = await session.scalar(select(DomainEventRecord.id))

    dispatcher = DomainEventDispatcher(
        JobRepository(),
        ai_experiments=(
            ("openai", "gpt-test", "prompt-v1", "policy-v1", "ai-view-v2"),
            ("anthropic", "claude-test", "prompt-v1", "policy-v1", "ai-view-v2"),
        ),
    )
    async with factory() as session, session.begin():
        assert await dispatcher.dispatch_pending(session) == 1

    async with factory() as session:
        jobs = list(
            (
                await session.scalars(
                    select(DurableJobRecord).where(
                        DurableJobRecord.job_type == JobType.RUN_AI_PROVIDER.value
                    )
                )
            ).all()
        )
        jobs.sort(key=lambda job: job.payload["provider"])
        assert [job.payload["provider"] for job in jobs] == ["anthropic", "openai"]
        assert [job.payload["model"] for job in jobs] == ["claude-test", "gpt-test"]
        assert [job.payload["snapshot_id"] for job in jobs] == [
            str(snapshot.snapshot_id),
            str(snapshot.snapshot_id),
        ]
        assert {job.dedupe_key for job in jobs} == {
            f"ai:{snapshot.snapshot_hash}:openai:gpt-test:prompt-v1:policy-v1:ai-view-v2",
            f"ai:{snapshot.snapshot_hash}:anthropic:claude-test:prompt-v1:policy-v1:ai-view-v2",
        }
        assert {job.priority for job in jobs} == {ai_job_priority("PREMATCH")}
        event = await session.get(DomainEventRecord, event_id)
        assert event is not None and event.processed_at is not None

    async with factory() as session, session.begin():
        assert await dispatcher.dispatch_pending(session) == 0
    await engine.dispose()


@pytest.mark.asyncio
async def test_reconciliation_does_not_infer_missing_experiment_after_ai_audit_exists() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    jobs = JobRepository()
    now = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)
    async with factory() as session, session.begin():
        snapshot = await _snapshot(session)
        session.add(
            AiDecisionRecord(
                snapshot_id=snapshot.snapshot_id,
                snapshot_hash=snapshot.snapshot_hash,
                provider="openai",
                model="gpt-test",
                model_version="gpt-test",
                prompt_version="prompt-v1",
                decision_policy_version="policy-v1",
                ai_view_version="ai-view-v2",
                request_started_at=now,
                parse_status="SUCCESS",
            )
        )

    reconciliation = ReconciliationService(
        jobs,
        EventRepository(),
        lease_seconds=120,
        ai_experiments=(
            ("openai", "gpt-test", "prompt-v1", "policy-v1", "ai-view-v2"),
            ("anthropic", "claude-test", "prompt-v1", "policy-v1", "ai-view-v2"),
        ),
        future_odds_horizons=(),
        ai_min_game_time_seconds=600,
    )
    async with factory() as session, session.begin():
        first = await reconciliation.run(session, now=now)
    async with factory() as session, session.begin():
        second = await reconciliation.run(session, now=now)

    assert first.ai_jobs == 0
    assert second.ai_jobs == 0
    async with factory() as session:
        job_count = await session.scalar(
            select(func.count())
            .select_from(DurableJobRecord)
            .where(DurableJobRecord.job_type == JobType.RUN_AI_PROVIDER.value)
        )
    assert job_count == 0
    await engine.dispose()


@pytest.mark.asyncio
async def test_ai_handler_persists_each_provider_before_slowest_finishes() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    snapshots = SnapshotRepository()
    fast = EventedProvider("openai")
    slow = EventedProvider("anthropic", delay=0.5)
    now = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)
    async with factory() as session, session.begin():
        snapshot = await _snapshot(session)

    handler = ApplicationJobHandlers(
        SimpleNamespace(
            settings=SimpleNamespace(ai_min_game_time_seconds=600),
            session_factory=factory,
            snapshots=snapshots,
            ai=AiCoordinator([fast, slow], timeout_seconds=5),
            health=HealthRegistry(),
            email_notifications=None,
        )
    )

    def _job(provider: EventedProvider) -> DurableJob:
        return DurableJob(
            id=uuid4(),
            job_type=JobType.RUN_AI_PROVIDER,
            dedupe_key=f"ai:{snapshot.snapshot_hash}:{provider.name}",
            payload={
                "snapshot_id": str(snapshot.snapshot_id),
                "provider": provider.name,
                "model": provider.model,
            },
            status=JobStatus.RUNNING,
            priority=100,
            not_before=now,
            created_at=now,
            attempt_count=1,
            max_attempts=8,
            locked_by="fixture",
            locked_at=now,
        )

    fast_task = asyncio.create_task(handler.run_ai(_job(fast)))
    slow_task = asyncio.create_task(handler.run_ai(_job(slow)))
    await asyncio.wait_for(slow.started.wait(), timeout=1)

    # GPT finishes first and its job is awaited to completion while Claude is
    # still sleeping. This proves the GPT record is already committed before
    # the slowest provider returns.
    await asyncio.wait_for(fast.finished.wait(), timeout=1)
    await fast_task
    assert not slow.finished.is_set()

    async with factory() as session:
        fast_record = await session.scalar(
            select(AiDecisionRecord).where(
                AiDecisionRecord.snapshot_id == snapshot.snapshot_id,
                AiDecisionRecord.provider == "openai",
            )
        )
        slow_record = await session.scalar(
            select(AiDecisionRecord).where(
                AiDecisionRecord.snapshot_id == snapshot.snapshot_id,
                AiDecisionRecord.provider == "anthropic",
            )
        )
    assert fast_record is not None
    assert slow_record is None
    await asyncio.wait_for(slow_task, timeout=1)

    async with factory() as session:
        records = list(
            (
                await session.scalars(
                    select(AiDecisionRecord).where(
                        AiDecisionRecord.snapshot_id == snapshot.snapshot_id
                    )
                )
            ).all()
        )
        assert {record.provider for record in records} == {"openai", "anthropic"}
        assert all(
            record.decision_persisted_at is not None
            and record.job_enqueued_at is not None
            and record.job_claimed_at is not None
            and record.input_prepare_started_at is not None
            and record.input_prepare_completed_at is not None
            for record in records
        )
    assert len(fast.inputs) == 1 and len(slow.inputs) == 1
    await engine.dispose()


@pytest.mark.asyncio
async def test_legacy_ai_job_payload_still_runs_all_experiments() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    snapshots = SnapshotRepository()
    providers = [EventedProvider("openai"), EventedProvider("anthropic")]
    now = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)
    async with factory() as session, session.begin():
        snapshot = await _snapshot(session)

    handler = ApplicationJobHandlers(
        SimpleNamespace(
            settings=SimpleNamespace(ai_min_game_time_seconds=600),
            session_factory=factory,
            snapshots=snapshots,
            ai=AiCoordinator(providers, timeout_seconds=5),
            health=HealthRegistry(),
            email_notifications=None,
        )
    )
    job = DurableJob(
        id=uuid4(),
        job_type=JobType.RUN_AI_PROVIDER,
        dedupe_key=f"ai:{snapshot.snapshot_hash}",
        payload={"snapshot_id": str(snapshot.snapshot_id)},
        status=JobStatus.RUNNING,
        priority=100,
        not_before=now,
        created_at=now,
        attempt_count=1,
        max_attempts=8,
        locked_by="fixture",
        locked_at=now,
    )
    await handler.run_ai(job)

    async with factory() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(AiDecisionRecord)
                .where(AiDecisionRecord.snapshot_id == snapshot.snapshot_id)
            )
            == 2
        )
    assert {provider.name for provider in providers if provider.inputs} == {
        "openai",
        "anthropic",
    }
    await engine.dispose()


@pytest.mark.asyncio
async def test_ai_record_versions_are_current_for_new_jobs() -> None:
    record = AiDecisionRecord(
        snapshot_id=uuid4(),
        snapshot_hash="fixture-hash",
        provider="openai",
        model="gpt-test",
        model_version="gpt-test",
        prompt_version=PROMPT_VERSION,
        decision_policy_version=DECISION_POLICY_VERSION,
        ai_view_version=AI_VIEW_VERSION,
        request_started_at=datetime(2026, 8, 15, tzinfo=UTC),
        parse_status="SUCCESS",
    )
    assert (
        record.provider,
        record.model,
        record.prompt_version,
        record.decision_policy_version,
        record.ai_view_version,
    ) == ("openai", "gpt-test", PROMPT_VERSION, DECISION_POLICY_VERSION, AI_VIEW_VERSION)
