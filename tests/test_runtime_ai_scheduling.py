from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import Base
from app.domain.events import DomainEventType
from app.domain.jobs import JobType
from app.events.dispatcher import DomainEventDispatcher
from app.events.outbox import EventRepository
from app.jobs.reconciliation import ReconciliationService
from app.jobs.repository import JobRepository
from app.models import DomainEventRecord, DurableJobRecord
from app.runtime_config.models import AiProviderConfigRecord
from app.snapshots.repository import SnapshotRepository


@pytest.mark.asyncio
async def test_runtime_provider_rows_override_startup_fanout_without_restart() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)

    async with factory() as session, session.begin():
        snapshot = await SnapshotRepository().persist(
            session,
            canonical_map_id=None,
            decision_at=now,
            mode="LIVE_BASIC",
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
        session.add_all(
            [
                AiProviderConfigRecord(
                    provider="openai",
                    slot="default",
                    enabled=False,
                    decisions_enabled=False,
                    base_url="https://api.openai.com/v1",
                    model="old-model",
                    reasoning_effort="high",
                    timeout_seconds=50,
                    api_key_secret_key="ai.openai.api_key",
                ),
                AiProviderConfigRecord(
                    provider="kimi",
                    slot="default",
                    enabled=True,
                    decisions_enabled=True,
                    base_url="https://api.moonshot.cn/v1",
                    model="hot-kimi-model",
                    reasoning_effort=None,
                    timeout_seconds=20,
                    api_key_secret_key="ai.kimi.api_key",
                ),
                DomainEventRecord(
                    event_type=DomainEventType.AI_DECISION_REQUESTED.value,
                    aggregate_type="decision_snapshot",
                    aggregate_id=str(snapshot.snapshot_id),
                    dedupe_key=f"ai:{snapshot.snapshot_hash}",
                    payload={"snapshot_id": str(snapshot.snapshot_id)},
                    occurred_at=now,
                ),
            ]
        )

    dispatcher = DomainEventDispatcher(
        JobRepository(),
        ai_experiments=(("openai", "startup-model", "p", "d", "v"),),
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
    assert [(job.payload["provider"], job.payload["model"]) for job in jobs] == [
        ("kimi", "hot-kimi-model")
    ]

    await engine.dispose()


@pytest.mark.asyncio
async def test_reconciliation_refreshes_runtime_provider_rows_before_ai_recovery() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)

    async with factory() as session, session.begin():
        await SnapshotRepository().persist(
            session,
            canonical_map_id=None,
            decision_at=now,
            mode="LIVE_BASIC",
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
        session.add_all(
            [
                AiProviderConfigRecord(
                    provider="openai",
                    slot="default",
                    enabled=False,
                    decisions_enabled=False,
                    base_url="https://api.openai.com/v1",
                    model="startup-model",
                    reasoning_effort="high",
                    timeout_seconds=50,
                    api_key_secret_key="ai.openai.api_key",
                ),
                AiProviderConfigRecord(
                    provider="kimi",
                    slot="default",
                    enabled=True,
                    decisions_enabled=True,
                    base_url="https://api.moonshot.cn/v1",
                    model="reconcile-kimi-model",
                    reasoning_effort=None,
                    timeout_seconds=20,
                    api_key_secret_key="ai.kimi.api_key",
                ),
            ]
        )

    reconciler = ReconciliationService(
        JobRepository(),
        EventRepository(),
        lease_seconds=30,
        ai_experiments=(("openai", "startup-model", "p", "d", "v"),),
        future_odds_horizons=(),
    )
    async with factory() as session, session.begin():
        result = await reconciler.run(session, now=now)
        assert result.ai_jobs == 1

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
    assert [(job.payload["provider"], job.payload["model"]) for job in jobs] == [
        ("kimi", "reconcile-kimi-model")
    ]

    await engine.dispose()
