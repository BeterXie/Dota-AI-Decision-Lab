from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.ai.base import AiProviderResponse, ai_experiment_key
from app.ai.jobs import ai_job_dedupe_key_for_experiment
from app.db import Base
from app.domain.decision import AiDecision
from app.domain.jobs import DurableJob, JobStatus, JobType
from app.jobs.handlers import ApplicationJobHandlers
from app.jobs.repository import JobRepository
from app.models import AiDecisionRecord, DecisionEmailNotificationRecord, DurableJobRecord
from app.notifications.email import DecisionEmailNotificationService, OutgoingEmail
from app.runtime.health import HealthRegistry
from app.runtime_config.ai_coordinator import RuntimeAiCoordinator
from app.runtime_config.service import _clear_active_experiment_cache
from app.snapshots.repository import SnapshotRepository


class _RecordingSender:
    def __init__(self) -> None:
        self.messages: list[OutgoingEmail] = []

    async def send(self, message: OutgoingEmail) -> str:
        self.messages.append(message)
        return "fixture-message-id"

    async def close(self) -> None:
        return None


class _BuyProvider:
    name = "openai"
    model = "fixture-openai"

    def __init__(self) -> None:
        self.calls = 0

    async def decide(self, _snapshot_input: str) -> AiProviderResponse:
        self.calls += 1
        return AiProviderResponse(
            raw_response={"model": self.model},
            decision=AiDecision(
                action="BUY_A",
                fair_probability_a=0.6,
                confidence=0.8,
                market_assessment="UNDERPRICED",
                minimum_acceptable_odds_a=1.8,
                stake=100.0,
                primary_reasons=["fixture edge"],
                counter_arguments=[],
                data_quality_concerns=[],
                blockers=[],
            ),
            model_version=self.model,
        )

    async def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_runtime_notification_waits_for_the_scheduled_provider_batch() -> None:
    _clear_active_experiment_cache()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    snapshots = SnapshotRepository()
    jobs = JobRepository()
    provider = _BuyProvider()
    sender = _RecordingSender()
    email_service = DecisionEmailNotificationService(
        session_factory=factory,
        jobs=jobs,
        sender=sender,
        sender_from="Decision Lab <alerts@example.com>",
        recipients=("owner@example.com",),
        subject_prefix="[Decision]",
    )
    now = datetime.now(UTC)

    async with factory() as session, session.begin():
        snapshot = await snapshots.persist(
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
        scheduled = (
            (provider.name, provider.model),
            ("anthropic", "fixture-anthropic"),
        )
        for scheduled_provider, scheduled_model in scheduled:
            experiment = ai_experiment_key(scheduled_provider, scheduled_model)
            await jobs.enqueue(
                session,
                job_type=JobType.RUN_AI_PROVIDER,
                dedupe_key=ai_job_dedupe_key_for_experiment(
                    snapshot.snapshot_hash,
                    experiment,
                ),
                payload={
                    "snapshot_id": str(snapshot.snapshot_id),
                    "provider": scheduled_provider,
                    "model": scheduled_model,
                },
                priority=40,
            )

    coordinator = RuntimeAiCoordinator([provider], timeout_seconds=1)
    handler = ApplicationJobHandlers(
        SimpleNamespace(
            settings=SimpleNamespace(
                ai_min_game_time_seconds=600,
                ai_notification_max_latency_seconds=50.0,
            ),
            session_factory=factory,
            snapshots=snapshots,
            ai=coordinator,
            health=HealthRegistry(),
            email_notifications=email_service,
        )
    )
    openai_experiment = ai_experiment_key(provider.name, provider.model)
    job = DurableJob(
        id=uuid4(),
        job_type=JobType.RUN_AI_PROVIDER,
        dedupe_key=ai_job_dedupe_key_for_experiment(
            snapshot.snapshot_hash,
            openai_experiment,
        ),
        payload={
            "snapshot_id": str(snapshot.snapshot_id),
            "provider": provider.name,
            "model": provider.model,
        },
        status=JobStatus.RUNNING,
        priority=40,
        not_before=now,
        created_at=now,
        attempt_count=1,
        max_attempts=8,
        locked_by="fixture",
        locked_at=now,
    )

    # Simulate an admin change after fan-out: the runtime coordinator now has
    # only OpenAI, while the durable batch already contains Anthropic too.
    assert coordinator.experiments == (openai_experiment,)
    await handler.run_ai(job)

    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(AiDecisionRecord)) == 1
        assert (
            await session.scalar(select(func.count()).select_from(DecisionEmailNotificationRecord))
            == 0
        )
        notification_jobs = await session.scalar(
            select(func.count())
            .select_from(DurableJobRecord)
            .where(DurableJobRecord.job_type == JobType.SEND_DECISION_EMAIL.value)
        )
        assert notification_jobs == 0

    assert provider.calls == 1
    assert sender.messages == []
    await engine.dispose()
