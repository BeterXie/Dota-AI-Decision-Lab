import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.ai.base import AiProviderResponse
from app.ai.context_profiles import (
    NO_PLAYER_FORM_CONTEXT_VERSION,
    SCHEMA_ALIGNED_CONTEXT_VERSION,
)
from app.ai.context_runner import AiContextExperimentRunner
from app.ai.coordinator import AiCoordinator
from app.db import Base
from app.domain.decision import AiDecision
from app.models import CanonicalMap
from app.snapshots.repository import SnapshotRepository

NOW = datetime(2026, 8, 18, 9, 30, tzinfo=UTC)


@dataclass
class FakeProvider:
    name: str = "openai"
    model: str = "gpt-5.6-terra"
    inputs: list[str] = field(default_factory=list)

    async def decide(self, snapshot_input: str) -> AiProviderResponse:
        self.inputs.append(snapshot_input)
        return AiProviderResponse(
            raw_response={"fixture": True},
            decision=AiDecision(
                action="NO_BUY",
                fair_probability_a=0.55,
                confidence=0.6,
                market_assessment="FAIR",
                minimum_acceptable_odds_a=None,
                stake=None,
                primary_reasons=["fixture"],
                blockers=[],
            ),
            model_version=self.model,
        )

    async def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_same_snapshot_persists_separate_context_experiments() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    provider = FakeProvider()
    runner = AiContextExperimentRunner(AiCoordinator([provider], timeout_seconds=1))

    async with factory() as session, session.begin():
        canonical_map = CanonicalMap(map_number=1)
        session.add(canonical_map)
        await session.flush()
        snapshot = await _persist_snapshot(session, canonical_map.id, NOW)
        aligned = await runner.run(
            session,
            snapshot,
            provider=provider.name,
            model=provider.model,
            ai_view_version=SCHEMA_ALIGNED_CONTEXT_VERSION,
        )
        no_form = await runner.run(
            session,
            snapshot,
            provider=provider.name,
            model=provider.model,
            ai_view_version=NO_PLAYER_FORM_CONTEXT_VERSION,
        )

    assert aligned.id != no_form.id
    assert aligned.snapshot_id == no_form.snapshot_id
    assert aligned.provider == no_form.provider == "openai"
    assert aligned.model == no_form.model == "gpt-5.6-terra"
    assert aligned.prompt_version == no_form.prompt_version == "decision-analyst-v5.1-output"
    assert (
        aligned.decision_policy_version
        == no_form.decision_policy_version
        == "shadow-tournament-portfolio-v3"
    )
    assert aligned.ai_view_version == SCHEMA_ALIGNED_CONTEXT_VERSION
    assert no_form.ai_view_version == NO_PLAYER_FORM_CONTEXT_VERSION
    assert aligned.ai_input_hash != no_form.ai_input_hash
    assert len(provider.inputs) == 2
    await engine.dispose()


@pytest.mark.asyncio
async def test_prior_decisions_are_isolated_by_full_context_experiment_identity() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    provider = FakeProvider()
    runner = AiContextExperimentRunner(AiCoordinator([provider], timeout_seconds=1))

    async with factory() as session, session.begin():
        canonical_map = CanonicalMap(map_number=1)
        session.add(canonical_map)
        await session.flush()
        first = await _persist_snapshot(session, canonical_map.id, NOW)
        second = await _persist_snapshot(session, canonical_map.id, NOW + timedelta(minutes=5))

        await runner.run(
            session,
            first,
            provider=provider.name,
            model=provider.model,
            ai_view_version=SCHEMA_ALIGNED_CONTEXT_VERSION,
        )
        await runner.run(
            session,
            first,
            provider=provider.name,
            model=provider.model,
            ai_view_version=NO_PLAYER_FORM_CONTEXT_VERSION,
        )
        prepared = await runner.prepare(
            session,
            second,
            provider=provider.name,
            model=provider.model,
            ai_view_version=NO_PLAYER_FORM_CONTEXT_VERSION,
        )

    payload = json.loads(prepared.provider_input)
    assert len(payload["prior_decisions"]) == 1
    assert payload["prior_decisions"][0]["decision_at"] == first.decision_at.isoformat()
    assert "base_strength" not in payload["history"]["players"][0]
    await engine.dispose()


def test_context_runner_rejects_non_baseline_model_and_production_view() -> None:
    runner = AiContextExperimentRunner(
        AiCoordinator([FakeProvider(model="gpt-5.6-terra")], timeout_seconds=1)
    )

    with pytest.raises(ValueError, match="registered challenger profile"):
        runner._validate_controlled_identity("openai", "gpt-5.6-terra", "ai-view-v6")
    with pytest.raises(ValueError, match="requires frozen openai model"):
        runner._validate_controlled_identity(
            "openai",
            "gpt-5.6-not-baseline",
            SCHEMA_ALIGNED_CONTEXT_VERSION,
        )


async def _persist_snapshot(session, canonical_map_id, decision_at):
    return await SnapshotRepository().persist(
        session,
        canonical_map_id=canonical_map_id,
        decision_at=decision_at,
        mode="PREMATCH",
        identity={
            "team_a": {"id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "name": "A"},
            "team_b": {"id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb", "name": "B"},
            "side_identity": {"status": "UNRESOLVED"},
            "series_context": {},
        },
        market={
            "market_type": "Winner",
            "match_stage": "Map 1",
            "quality": {"eligible": True, "warnings": []},
            "observations": [],
        },
        draft=None,
        history={
            "team_a": {"base_rating": 1500.0, "recent_form": 0.6},
            "team_b": {"base_rating": 1490.0, "recent_form": 0.55},
            "players_a": [
                {
                    "position": 1,
                    "base_strength": 0.64,
                    "recent_form": 0.71,
                    "recent_form_confidence": 0.8,
                    "current_hero": 1,
                    "player_hero_strength": 0.76,
                    "player_hero_sample": 42,
                    "player_hero_confidence": 0.85,
                    "position_fit": 0.91,
                    "knowledge_cutoff": decision_at,
                }
            ],
            "players_b": [],
            "coverage": {"player_form_ready_count": 1, "player_hero_ready_count": 1},
        },
        live=None,
        quality={"eligible": True, "blockers": [], "warnings": []},
    )
