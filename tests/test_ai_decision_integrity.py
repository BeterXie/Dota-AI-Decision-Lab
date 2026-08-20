import asyncio
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.ai.base import AiProviderResponse
from app.ai.coordinator import AiCoordinator
from app.ai.lanes import AiExperimentLaneRegistry
from app.ai.replay import AiExperimentReplayService
from app.db import Base
from app.domain.decision import AiDecision
from app.domain.jobs import DurableJob, JobStatus, JobType
from app.jobs.handlers import ApplicationJobHandlers, _new_buy_decisions
from app.jobs.repository import JobRepository
from app.models import (
    AiDecisionRecord,
    CanonicalMap,
    CanonicalSeries,
    CanonicalTeam,
    DurableJobRecord,
)
from app.runtime.health import HealthRegistry
from app.snapshots.repository import SnapshotRepository


class SequentialProvider:
    name = "openai"
    model = "fixture-gpt"

    def __init__(self) -> None:
        self.inputs: list[dict] = []
        self.first_started = asyncio.Event()
        self.release_first = asyncio.Event()

    async def decide(self, snapshot_input: str) -> AiProviderResponse:
        self.inputs.append(json.loads(snapshot_input))
        if len(self.inputs) == 1:
            self.first_started.set()
            await self.release_first.wait()
            decision = AiDecision(
                action="BUY_A",
                fair_probability_a=0.62,
                confidence=0.75,
                market_assessment="UNDERPRICED",
                minimum_acceptable_odds_a=1.75,
                stake=100,
                primary_reasons=["fixture"],
                counter_arguments=[],
                data_quality_concerns=[],
                blockers=[],
            )
        else:
            decision = AiDecision(
                action="NO_BUY",
                fair_probability_a=0.52,
                confidence=0.6,
                market_assessment="FAIR",
                minimum_acceptable_odds_a=None,
                stake=None,
                primary_reasons=["fixture"],
                counter_arguments=[],
                data_quality_concerns=[],
                blockers=[],
            )
        return AiProviderResponse(
            raw_response={"call": len(self.inputs)},
            decision=decision,
            model_version=self.model,
        )

    async def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_lane_registry_orders_contending_checkpoints_by_decision_time() -> None:
    lanes = AiExperimentLaneRegistry()
    acquired: list[str] = []
    base = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)

    async def enter(label: str, decision_at: datetime) -> None:
        async with lanes.hold("map:openai:gpt", decision_at):
            acquired.append(label)
            await asyncio.sleep(0)

    late = asyncio.create_task(enter("15m", base + timedelta(minutes=15)))
    early = asyncio.create_task(enter("10m", base + timedelta(minutes=10)))
    await asyncio.gather(late, early)

    assert acquired == ["10m", "15m"]


@pytest.mark.asyncio
async def test_same_experiment_checkpoint_waits_for_prior_persist_before_prepare() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    snapshots = SnapshotRepository()
    provider = SequentialProvider()
    coordinator = AiCoordinator([provider], timeout_seconds=5, virtual_bankroll=10_000)
    base = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)

    async with factory() as session, session.begin():
        team_a = CanonicalTeam(name="A")
        team_b = CanonicalTeam(name="B")
        session.add_all((team_a, team_b))
        await session.flush()
        series = CanonicalSeries(team_a_id=team_a.id, team_b_id=team_b.id)
        session.add(series)
        await session.flush()
        canonical_map = CanonicalMap(series_id=series.id, map_number=1, valve_match_id=123456)
        session.add(canonical_map)
        await session.flush()
        identity = {
            "series_id": str(series.id),
            "map_id": str(canonical_map.id),
            "valve_match_id": canonical_map.valve_match_id,
            "team_a": {"id": str(team_a.id), "name": "A"},
            "team_b": {"id": str(team_b.id), "name": "B"},
        }
        first = await snapshots.persist(
            session,
            canonical_map_id=canonical_map.id,
            decision_at=base,
            mode="LIVE_BASIC",
            identity=identity,
            market={},
            draft=None,
            history={},
            live={"game_time_seconds": 600},
            quality={"eligible": True, "blockers": [], "warnings": []},
        )
        second = await snapshots.persist(
            session,
            canonical_map_id=canonical_map.id,
            decision_at=base + timedelta(minutes=5),
            mode="LIVE_BASIC",
            identity=identity,
            market={},
            draft=None,
            history={},
            live={"game_time_seconds": 900},
            quality={"eligible": True, "blockers": [], "warnings": []},
        )

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
            email_notifications=None,
            wechat_clawbot=None,
        )
    )

    def job(snapshot_id, created_at: datetime) -> DurableJob:
        return DurableJob(
            id=uuid4(),
            job_type=JobType.RUN_AI_PROVIDER,
            dedupe_key=f"fixture:{snapshot_id}",
            payload={
                "snapshot_id": str(snapshot_id),
                "provider": provider.name,
                "model": provider.model,
            },
            status=JobStatus.RUNNING,
            priority=40,
            not_before=created_at,
            created_at=created_at,
            attempt_count=1,
            max_attempts=8,
            locked_by="fixture",
            locked_at=created_at,
        )

    first_task = asyncio.create_task(handler.run_ai(job(first.snapshot_id, base)))
    await asyncio.wait_for(provider.first_started.wait(), timeout=1)
    second_task = asyncio.create_task(
        handler.run_ai(job(second.snapshot_id, base + timedelta(minutes=5)))
    )
    await asyncio.sleep(0.05)
    assert len(provider.inputs) == 1

    provider.release_first.set()
    await asyncio.gather(first_task, second_task)

    assert len(provider.inputs) == 2
    assert provider.inputs[0]["prior_decisions"] == []
    second_input = provider.inputs[1]
    assert len(second_input["prior_decisions"]) == 1
    assert second_input["prior_decisions"][0]["action"] == "BUY_A"
    assert second_input["virtual_bankroll"]["bankroll_before"] == 9900.0

    async with factory() as session:
        records = list(
            (
                await session.scalars(
                    select(AiDecisionRecord).order_by(AiDecisionRecord.request_started_at)
                )
            ).all()
        )
    assert len(records) == 2
    await engine.dispose()


@pytest.mark.asyncio
async def test_explicit_replay_is_marked_and_deduplicated() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    snapshots = SnapshotRepository()
    now = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)

    async with factory() as session, session.begin():
        snapshot = await snapshots.persist(
            session,
            canonical_map_id=None,
            decision_at=now,
            mode="LIVE_BASIC",
            identity={"team_a": {"id": "a"}, "team_b": {"id": "b"}},
            market={},
            draft=None,
            history={},
            live={"game_time_seconds": 600},
            quality={"eligible": True, "blockers": [], "warnings": []},
        )
        session.add(
            AiDecisionRecord(
                snapshot_id=snapshot.snapshot_id,
                snapshot_hash=snapshot.snapshot_hash,
                provider="openai",
                model="fixture-gpt",
                model_version="fixture-gpt",
                prompt_version="old-prompt",
                decision_policy_version="policy-v1",
                ai_view_version="view-v1",
                request_started_at=now,
                parse_status="SUCCESS",
            )
        )

    replay = AiExperimentReplayService(
        JobRepository(),
        experiments=(("openai", "fixture-gpt", "new-prompt", "policy-v1", "view-v1"),),
    )
    async with factory() as session, session.begin():
        assert await replay.enqueue_snapshots(session, snapshot_ids=(snapshot.snapshot_id,)) == 1
    async with factory() as session, session.begin():
        assert await replay.enqueue_snapshots(session, snapshot_ids=(snapshot.snapshot_id,)) == 0

    async with factory() as session:
        job_record = await session.scalar(
            select(DurableJobRecord).where(
                DurableJobRecord.job_type == JobType.RUN_AI_PROVIDER.value
            )
        )
        count_jobs = await session.scalar(select(func.count()).select_from(DurableJobRecord))
    assert count_jobs == 1
    assert job_record is not None
    assert job_record.payload["experiment_replay"] is True
    assert job_record.priority == 160
    await engine.dispose()


def _buy_record(action: str, provider: str = "openai") -> AiDecisionRecord:
    now = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)
    return AiDecisionRecord(
        snapshot_id=uuid4(),
        snapshot_hash="fixture",
        provider=provider,
        model="fixture-model",
        model_version="fixture-model",
        prompt_version="prompt",
        decision_policy_version="policy",
        ai_view_version="view",
        request_started_at=now,
        parse_status="SUCCESS",
        normalized_response={"action": action},
    )


def test_buy_notification_transition_compares_latest_action_not_historical_set() -> None:
    buy_a = _buy_record("BUY_A")
    buy_b = _buy_record("BUY_B")

    assert _new_buy_decisions([buy_a], {("openai", "fixture-model"): "BUY_A"}) == []
    assert _new_buy_decisions([buy_b], {("openai", "fixture-model"): "BUY_A"}) == [buy_b]
    assert _new_buy_decisions([buy_a], {("openai", "fixture-model"): "BUY_B"}) == [buy_a]
