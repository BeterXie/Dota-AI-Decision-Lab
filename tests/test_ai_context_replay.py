from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from math import log
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.ai.base import AiProviderResponse
from app.ai.context_profiles import (
    NO_PLAYER_FORM_CONTEXT_VERSION,
    REPLAY_PRODUCTION_CONTEXT_VERSION,
    SCHEMA_ALIGNED_CONTEXT_VERSION,
)
from app.ai.context_replay import (
    ContextReplayExecutor,
    ContextReplayPlanner,
)
from app.ai.context_runner import AiContextExperimentRunner
from app.ai.coordinator import AiCoordinator
from app.db import Base
from app.domain.decision import AiDecision
from app.evaluation.portfolio_models import (
    TournamentPortfolioAccountRecord,
    TournamentPortfolioPositionRecord,
)
from app.models import (
    AiDecisionRecord,
    CanonicalMap,
    DecisionEvaluationRecord,
    MapResultRecord,
)
from app.snapshots.repository import SnapshotRepository

NOW = datetime(2026, 8, 18, 8, 0, tzinfo=UTC)
TEAM_A = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
TEAM_B = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")


@dataclass
class ReplayProvider:
    name: str = "openai"
    model: str = "gpt-5.6-terra"
    fail_on_call: int | None = None
    inputs: list[str] = field(default_factory=list)

    async def decide(self, snapshot_input: str) -> AiProviderResponse:
        self.inputs.append(snapshot_input)
        if self.fail_on_call is not None and len(self.inputs) == self.fail_on_call:
            raise RuntimeError("fixture provider failure")
        return AiProviderResponse(
            raw_response={"fixture": True},
            decision=AiDecision(
                action="NO_BUY",
                fair_probability_a=0.58,
                confidence=0.7,
                market_assessment="FAIR",
                minimum_acceptable_odds_a=None,
                stake=None,
                primary_reasons=["matched replay fixture"],
                blockers=[],
            ),
            model_version=self.model,
        )

    async def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_planner_selects_earliest_evaluable_settled_baseline_and_dedupes_profiles() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session, session.begin():
        map_one = CanonicalMap(map_number=1)
        map_unsettled = CanonicalMap(map_number=2)
        map_conflict = CanonicalMap(map_number=3)
        session.add_all([map_one, map_unsettled, map_conflict])
        await session.flush()

        earliest = await _baseline_snapshot(session, map_one.id, NOW)
        await _baseline_snapshot(
            session,
            map_one.id,
            NOW + timedelta(minutes=5),
            result=False,
        )
        await _baseline_snapshot(
            session, map_unsettled.id, NOW + timedelta(minutes=10), result=False
        )
        await _baseline_snapshot(
            session,
            map_conflict.id,
            NOW + timedelta(minutes=15),
            provider_conflict=True,
        )
        session.add(
            _experimental_record(
                earliest,
                REPLAY_PRODUCTION_CONTEXT_VERSION,
            )
        )
        await session.flush()

        plan = await ContextReplayPlanner().build_plan(
            session,
            provider="openai",
            profiles=[NO_PLAYER_FORM_CONTEXT_VERSION],
            max_maps=10,
            max_calls=10,
        )

    assert plan.model == "gpt-5.6-terra"
    assert plan.requested_profiles == (NO_PLAYER_FORM_CONTEXT_VERSION,)
    assert plan.expanded_profiles == (
        REPLAY_PRODUCTION_CONTEXT_VERSION,
        SCHEMA_ALIGNED_CONTEXT_VERSION,
        NO_PLAYER_FORM_CONTEXT_VERSION,
    )
    assert plan.map_count == 1
    assert plan.potential_calls == 3
    assert plan.already_completed == 1
    assert plan.planned_calls == 2
    assert {entry.ai_view_version for entry in plan.entries} == {
        SCHEMA_ALIGNED_CONTEXT_VERSION,
        NO_PLAYER_FORM_CONTEXT_VERSION,
    }
    assert {entry.snapshot_id for entry in plan.entries} == {earliest.snapshot_id}
    await engine.dispose()


@pytest.mark.asyncio
async def test_planner_call_cap_fails_closed() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session, session.begin():
        canonical_map = CanonicalMap(map_number=1)
        session.add(canonical_map)
        await session.flush()
        await _baseline_snapshot(session, canonical_map.id, NOW)
        with pytest.raises(ValueError, match="exceed max_calls"):
            await ContextReplayPlanner().build_plan(
                session,
                provider="openai",
                profiles=[NO_PLAYER_FORM_CONTEXT_VERSION],
                max_maps=1,
                max_calls=2,
            )
    await engine.dispose()


@pytest.mark.asyncio
async def test_executor_requires_exact_confirmation_evaluates_and_never_records_portfolio() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session, session.begin():
        canonical_map = CanonicalMap(map_number=1)
        session.add(canonical_map)
        await session.flush()
        await _baseline_snapshot(session, canonical_map.id, NOW)
        plan = await ContextReplayPlanner().build_plan(
            session,
            provider="openai",
            profiles=[NO_PLAYER_FORM_CONTEXT_VERSION],
            max_maps=1,
            max_calls=3,
        )

    provider = ReplayProvider()
    coordinator = AiCoordinator([provider], timeout_seconds=1, portfolio=None)
    executor = ContextReplayExecutor(factory, AiContextExperimentRunner(coordinator))
    with pytest.raises(ValueError, match="does not match fresh plan"):
        await executor.execute(plan, confirm_calls=2)
    assert provider.inputs == []

    result = await executor.execute(plan, confirm_calls=3)
    assert result["succeeded"] == 3
    assert result["failed"] == 0
    assert len(provider.inputs) == 3

    async with factory() as session:
        experiment_rows = list(
            (
                await session.scalars(
                    select(AiDecisionRecord).where(
                        AiDecisionRecord.ai_view_version.in_(plan.expanded_profiles)
                    )
                )
            ).all()
        )
        assert {row.ai_view_version for row in experiment_rows} == set(plan.expanded_profiles)
        evaluation_count = await session.scalar(
            select(func.count(DecisionEvaluationRecord.id)).where(
                DecisionEvaluationRecord.ai_decision_id.in_([row.id for row in experiment_rows])
            )
        )
        assert evaluation_count == 3
        assert await session.scalar(select(func.count(TournamentPortfolioAccountRecord.id))) == 0
        assert await session.scalar(select(func.count(TournamentPortfolioPositionRecord.id))) == 0
    await coordinator.close()
    await engine.dispose()


@pytest.mark.asyncio
async def test_executor_commits_each_call_and_keeps_failed_attempt_audit() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session, session.begin():
        canonical_map = CanonicalMap(map_number=1)
        session.add(canonical_map)
        await session.flush()
        await _baseline_snapshot(session, canonical_map.id, NOW)
        plan = await ContextReplayPlanner().build_plan(
            session,
            provider="openai",
            profiles=[NO_PLAYER_FORM_CONTEXT_VERSION],
            max_maps=1,
            max_calls=3,
        )

    provider = ReplayProvider(fail_on_call=2)
    coordinator = AiCoordinator([provider], timeout_seconds=1, portfolio=None)
    result = await ContextReplayExecutor(
        factory,
        AiContextExperimentRunner(coordinator),
    ).execute(plan, confirm_calls=3)

    assert result["succeeded"] == 2
    assert result["failed"] == 1
    failed = [item for item in result["results"] if item["status"] == "FAILED"]
    assert failed[0]["parse_status"] == "FAILED"
    assert "fixture provider failure" in failed[0]["error"]
    async with factory() as session:
        persisted = list(
            (
                await session.scalars(
                    select(AiDecisionRecord).where(
                        AiDecisionRecord.ai_view_version.in_(plan.expanded_profiles)
                    )
                )
            ).all()
        )
        assert len(persisted) == 3
        assert sum(row.parse_status == "SUCCESS" for row in persisted) == 2
        assert sum(row.parse_status == "FAILED" for row in persisted) == 1
    await coordinator.close()
    await engine.dispose()


async def _baseline_snapshot(
    session,
    canonical_map_id: UUID,
    decision_at: datetime,
    *,
    result: bool = True,
    provider_conflict: bool = False,
):
    snapshot = await SnapshotRepository().persist(
        session,
        canonical_map_id=canonical_map_id,
        decision_at=decision_at,
        mode="PREMATCH",
        identity={
            "team_a": {"id": str(TEAM_A), "name": "A"},
            "team_b": {"id": str(TEAM_B), "name": "B"},
            "side_identity": {"status": "UNRESOLVED"},
            "series_context": {},
        },
        market={
            "market_type": "Winner",
            "match_stage": "Map 1",
            "quality": {"eligible": True, "warnings": []},
            "observations": [
                {"selection_team_id": str(TEAM_A), "price": 1.9},
                {"selection_team_id": str(TEAM_B), "price": 2.0},
            ],
        },
        draft=None,
        history={
            "team_a": {"base_rating": 1510.0, "recent_form": 0.62},
            "team_b": {"base_rating": 1490.0, "recent_form": 0.55},
            "players_a": [
                {
                    "position": 1,
                    "base_strength": 0.64,
                    "recent_form": 0.71,
                    "recent_form_confidence": 0.8,
                    "player_hero_strength": 0.76,
                    "player_hero_sample": 42,
                    "player_hero_confidence": 0.85,
                    "position_fit": 0.91,
                }
            ],
            "players_b": [],
            "coverage": {"player_form_ready_count": 1, "player_hero_ready_count": 1},
        },
        live=None,
        quality={"eligible": True, "blockers": [], "warnings": []},
    )
    record = AiDecisionRecord(
        snapshot_id=snapshot.snapshot_id,
        snapshot_hash=snapshot.snapshot_hash,
        provider="openai",
        model="gpt-5.6-terra",
        model_version="gpt-5.6-terra",
        prompt_version="decision-analyst-v5.1-output",
        decision_policy_version="shadow-tournament-portfolio-v3",
        ai_view_version="ai-view-v6",
        ai_input_hash=f"baseline-{uuid4()}",
        bankroll_before=10_000,
        request_started_at=decision_at,
        response_received_at=decision_at + timedelta(seconds=1),
        latency_seconds=1.0,
        normalized_response={
            "action": "NO_BUY",
            "fair_probability_a": 0.6,
            "confidence": 0.7,
            "market_assessment": "FAIR",
            "minimum_acceptable_odds_a": None,
            "stake": None,
            "primary_reasons": ["baseline fixture"],
            "blockers": [],
        },
        raw_response={"fixture": True},
        parse_status="SUCCESS",
    )
    session.add(record)
    await session.flush()
    probability = 0.6
    session.add(
        DecisionEvaluationRecord(
            ai_decision_id=record.id,
            brier_score=(probability - 1.0) ** 2,
            log_loss=-log(probability),
            metrics_version="replay-fixture-v1",
        )
    )
    if result:
        session.add(
            MapResultRecord(
                canonical_map_id=canonical_map_id,
                winner_team_id=TEAM_A,
                basic_first_usable_at=decision_at + timedelta(hours=1),
                provider_conflict=provider_conflict,
            )
        )
    await session.flush()
    return snapshot


def _experimental_record(snapshot, ai_view_version: str) -> AiDecisionRecord:
    return AiDecisionRecord(
        snapshot_id=snapshot.snapshot_id,
        snapshot_hash=snapshot.snapshot_hash,
        provider="openai",
        model="gpt-5.6-terra",
        model_version="gpt-5.6-terra",
        prompt_version="decision-analyst-v5.1-output",
        decision_policy_version="shadow-tournament-portfolio-v3",
        ai_view_version=ai_view_version,
        ai_input_hash=f"experiment-{uuid4()}",
        bankroll_before=10_000,
        request_started_at=snapshot.decision_at,
        response_received_at=snapshot.decision_at + timedelta(seconds=1),
        latency_seconds=1.0,
        normalized_response={
            "action": "NO_BUY",
            "fair_probability_a": 0.6,
            "confidence": 0.7,
            "market_assessment": "FAIR",
            "minimum_acceptable_odds_a": None,
            "stake": None,
            "primary_reasons": ["existing experiment fixture"],
            "blockers": [],
        },
        raw_response={"fixture": True},
        parse_status="SUCCESS",
    )
