import asyncio
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.ai.base import (
    AI_VIEW_VERSION,
    DECISION_POLICY_VERSION,
    PROMPT_VERSION,
    AiProviderFailure,
    AiProviderResponse,
    AiProviderUsage,
)
from app.ai.coordinator import AiCoordinator
from app.db import Base
from app.domain.decision import AiDecision
from app.models import AiDecisionRecord, CanonicalMap
from app.snapshots.repository import SnapshotRepository


def _decision() -> AiDecision:
    return AiDecision(
        action="NO_BUY",
        fair_probability_a=None,
        confidence=0.5,
        market_assessment="UNKNOWN",
        minimum_acceptable_odds_a=None,
        primary_reasons=["No edge"],
        counter_arguments=["Pricing could move"],
        data_quality_concerns=["Sample is limited"],
        blockers=[],
    )


@dataclass
class FakeProvider:
    name: str
    model: str = "fixture-model"
    mode: str = "success"
    decision: AiDecision | None = None
    inputs: list[str] = field(default_factory=list)
    usage: AiProviderUsage | None = None

    async def decide(self, snapshot_input: str) -> AiProviderResponse:
        self.inputs.append(snapshot_input)
        if self.mode == "parse_failure":
            raise AiProviderFailure(
                "invalid fixture JSON",
                parse_status="PARSE_FAILED",
                raw_response={"text": "not-json"},
            )
        if self.mode == "timeout":
            await asyncio.sleep(1)
        return AiProviderResponse(
            raw_response={"provider": self.name},
            decision=self.decision or _decision(),
            model_version=self.model,
            usage=self.usage,
        )

    async def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_same_snapshot_goes_to_all_models_and_failures_are_isolated() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    providers = [
        FakeProvider(
            "ok",
            usage=AiProviderUsage(
                input_tokens=1000,
                cached_input_tokens=750,
                reasoning_tokens=120,
                output_tokens=180,
                total_tokens=1180,
            ),
        ),
        FakeProvider("bad", mode="parse_failure"),
        FakeProvider("slow", mode="timeout"),
    ]

    async with factory() as session, session.begin():
        snapshot = await SnapshotRepository().persist(
            session,
            canonical_map_id=None,
            decision_at=datetime(2026, 1, 1, tzinfo=UTC),
            mode="PREMATCH",
            identity={"team_a": "A", "team_b": "B"},
            market={"price_a": "2.00", "price_b": "2.00"},
            draft=None,
            history={"team_a": None, "team_b": None},
            live=None,
            quality={"eligible": True, "blockers": [], "warnings": []},
        )
        records = await AiCoordinator(providers, timeout_seconds=0.01).run_all(session, snapshot)

    assert len({provider.inputs[0] for provider in providers}) == 1
    assert {record.provider: record.parse_status for record in records} == {
        "ok": "SUCCESS",
        "bad": "PARSE_FAILED",
        "slow": "TIMEOUT",
    }
    ok = next(record for record in records if record.provider == "ok")
    assert (ok.input_tokens, ok.cached_input_tokens, ok.reasoning_tokens) == (1000, 750, 120)
    assert (ok.output_tokens, ok.total_tokens) == (180, 1180)
    bad = next(record for record in records if record.provider == "bad")
    assert bad.normalized_response is None
    assert bad.raw_response == {"text": "not-json"}
    await engine.dispose()


@pytest.mark.asyncio
async def test_new_model_version_can_rerun_same_snapshot() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        snapshot = await SnapshotRepository().persist(
            session,
            canonical_map_id=None,
            decision_at=datetime(2026, 1, 1, tzinfo=UTC),
            mode="PREMATCH",
            identity={},
            market={},
            draft=None,
            history={},
            live=None,
            quality={"eligible": True},
        )
        first = await AiCoordinator(
            [FakeProvider("openai", model="fixture-v1")], timeout_seconds=1
        ).run_all(session, snapshot)
        second = await AiCoordinator(
            [FakeProvider("openai", model="fixture-v2")], timeout_seconds=1
        ).run_all(session, snapshot)

    assert first[0].id != second[0].id
    assert first[0].model == "fixture-v1"
    assert second[0].model == "fixture-v2"
    await engine.dispose()


@pytest.mark.asyncio
async def test_ai_view_version_bump_reruns_and_records_input_hash() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        snapshot = await SnapshotRepository().persist(
            session,
            canonical_map_id=None,
            decision_at=datetime(2026, 1, 1, tzinfo=UTC),
            mode="PREMATCH",
            identity={},
            market={},
            draft=None,
            history={},
            live=None,
            quality={"eligible": True},
        )
        # A legacy decision produced by the old ai-view-v2 semantics with the
        # SAME provider/model/prompt/policy must not block the v4 run.
        session.add(
            AiDecisionRecord(
                id=uuid4(),
                snapshot_id=snapshot.snapshot_id,
                snapshot_hash=snapshot.snapshot_hash,
                provider="openai",
                model="fixture-model",
                model_version="fixture-model",
                prompt_version=PROMPT_VERSION,
                decision_policy_version=DECISION_POLICY_VERSION,
                ai_view_version="ai-view-v2",
                request_started_at=datetime(2026, 1, 1, tzinfo=UTC),
                parse_status="SUCCESS",
            )
        )
        await session.flush()
        records = await AiCoordinator(
            [FakeProvider("openai", model="fixture-model")], timeout_seconds=1
        ).run_all(session, snapshot)

    assert len(records) == 1
    record = records[0]
    assert record.ai_view_version == AI_VIEW_VERSION
    assert record.ai_view_version == "ai-view-v6"
    assert record.ai_input_hash is not None and len(record.ai_input_hash) == 64

    async with factory() as session, session.begin():
        again = await AiCoordinator(
            [FakeProvider("openai", model="fixture-model")], timeout_seconds=1
        ).run_all(session, snapshot)
    assert again[0].id == record.id
    await engine.dispose()


@pytest.mark.asyncio
async def test_provider_receives_versioned_context_summary() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    provider = FakeProvider("openai")

    async with factory() as session, session.begin():
        snapshot = await SnapshotRepository().persist(
            session,
            canonical_map_id=None,
            decision_at=datetime(2026, 1, 1, tzinfo=UTC),
            mode="PREMATCH",
            identity={
                "team_a": {"id": "team-a", "name": "A"},
                "team_b": {"id": "team-b", "name": "B"},
            },
            market={
                "observations": [
                    {
                        "selection_team_id": "team-a",
                        "price": "1.70",
                        "fair_probability": 0.6,
                        "implied_probability": 0.588,
                    },
                    {
                        "selection_team_id": "team-b",
                        "price": "2.30",
                        "fair_probability": 0.4,
                        "implied_probability": 0.435,
                    },
                ],
                "quality": {"eligible": True},
            },
            draft=None,
            history={},
            live=None,
            quality={"eligible": True, "blockers": [], "warnings": []},
        )
        records = await AiCoordinator([provider], timeout_seconds=1).run_all(session, snapshot)

    payload = json.loads(provider.inputs[0])
    assert "base_ai_view_version" not in payload
    assert "ai_view_version" not in payload
    assert "context_summary_version" not in payload["ai_context_summary"]
    assert "policy" not in payload["virtual_bankroll"]
    assert payload["ai_context_summary"]["market_signal"]["favorite"] == "A"
    assert records[0].ai_view_version == "ai-view-v6"
    await engine.dispose()


def _buy_decision(stake: float | None) -> AiDecision:
    return AiDecision(
        action="BUY_A",
        fair_probability_a=0.61,
        confidence=0.7,
        market_assessment="UNDERPRICED",
        minimum_acceptable_odds_a=1.65,
        stake=stake,
        primary_reasons=["价格与阵容优势一致"],
        counter_arguments=["后期存在变数"],
        data_quality_concerns=["样本有限"],
        blockers=[],
    )


async def _persist_fixture_snapshot(session, *, canonical_map_id, decision_at):
    return await SnapshotRepository().persist(
        session,
        canonical_map_id=canonical_map_id,
        decision_at=decision_at,
        mode="LIVE_BASIC",
        identity={"team_a": {"id": "team-a", "name": "A"}, "team_b": {"id": "team-b", "name": "B"}},
        market={},
        draft=None,
        history={},
        live=None,
        quality={"eligible": True, "blockers": [], "warnings": []},
    )


@pytest.mark.asyncio
async def test_prior_decisions_and_virtual_bankroll_flow_into_next_input() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime(2026, 1, 1, 12, 30, tzinfo=UTC)
    provider = FakeProvider("openai", model="fixture-model")

    async with factory() as session, session.begin():
        canonical_map = CanonicalMap(map_number=1)
        session.add(canonical_map)
        await session.flush()
        first = await _persist_fixture_snapshot(
            session,
            canonical_map_id=canonical_map.id,
            decision_at=now - timedelta(minutes=5),
        )
        first_records = await AiCoordinator(
            [FakeProvider("openai", model="fixture-model", decision=_buy_decision(500.0))],
            timeout_seconds=1,
            virtual_bankroll=10_000.0,
        ).run_all(session, first)
        second = await _persist_fixture_snapshot(
            session,
            canonical_map_id=canonical_map.id,
            decision_at=now,
        )
        second_records = await AiCoordinator(
            [provider], timeout_seconds=1, virtual_bankroll=10_000.0
        ).run_all(session, second)

    assert first_records[0].stake == 500.0
    assert first_records[0].bankroll_before == 10_000.0
    second_input = json.loads(provider.inputs[0])
    assert second_input["virtual_bankroll"]["initial"] == 10_000.0
    assert second_input["virtual_bankroll"]["bankroll_before"] == 9_500.0
    assert second_input["virtual_bankroll"]["unsettled_stakes"] == 500.0
    assert len(second_input["prior_decisions"]) == 1
    prior = second_input["prior_decisions"][0]
    assert prior["action"] == "BUY_A"
    assert prior["stake"] == 500.0
    assert prior["bankroll_before"] == 10_000.0
    assert prior["bankroll_after"] == 9_500.0
    assert "counter_arguments" not in prior
    assert "data_quality_concerns" not in prior
    assert prior["blockers"] == []
    assert second_records[0].bankroll_before == 9_500.0
    await engine.dispose()


@pytest.mark.asyncio
async def test_stake_above_bankroll_is_policy_failed_and_raw_is_preserved() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session, session.begin():
        snapshot = await SnapshotRepository().persist(
            session,
            canonical_map_id=None,
            decision_at=datetime(2026, 1, 1, tzinfo=UTC),
            mode="PREMATCH",
            identity={},
            market={},
            draft=None,
            history={},
            live=None,
            quality={"eligible": True},
        )
        records = await AiCoordinator(
            [FakeProvider("openai", decision=_buy_decision(50_000.0))],
            timeout_seconds=1,
            virtual_bankroll=1_000.0,
        ).run_all(session, snapshot)

    record = records[0]
    assert record.parse_status == "POLICY_FAILED"
    assert record.normalized_response is None
    assert record.stake is None
    assert record.bankroll_before == 1_000.0
    assert record.raw_response == {"provider": "openai"}
    assert "exceeds available bankroll" in (record.error or "")
    await engine.dispose()


@pytest.mark.asyncio
async def test_no_buy_with_nonzero_stake_is_policy_failed() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    invalid = _decision().model_copy(update={"stake": 100.0})

    async with factory() as session, session.begin():
        snapshot = await SnapshotRepository().persist(
            session,
            canonical_map_id=None,
            decision_at=datetime(2026, 1, 1, tzinfo=UTC),
            mode="PREMATCH",
            identity={},
            market={},
            draft=None,
            history={},
            live=None,
            quality={"eligible": True},
        )
        records = await AiCoordinator(
            [FakeProvider("openai", decision=invalid)],
            timeout_seconds=1,
            virtual_bankroll=1_000.0,
        ).run_all(session, snapshot)

    record = records[0]
    assert record.parse_status == "POLICY_FAILED"
    assert record.normalized_response is None
    await engine.dispose()


@pytest.mark.asyncio
async def test_bankroll_accounting_uses_all_history_while_context_window_is_limited() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime(2026, 1, 1, 12, 30, tzinfo=UTC)
    provider = FakeProvider("openai", model="fixture-model")

    async with factory() as session, session.begin():
        canonical_map = CanonicalMap(map_number=1)
        session.add(canonical_map)
        await session.flush()
        first = await _persist_fixture_snapshot(
            session,
            canonical_map_id=canonical_map.id,
            decision_at=now - timedelta(minutes=10),
        )
        await AiCoordinator(
            [FakeProvider("openai", model="fixture-model", decision=_buy_decision(400.0))],
            timeout_seconds=1,
            virtual_bankroll=10_000.0,
        ).run_all(session, first)
        second = await _persist_fixture_snapshot(
            session,
            canonical_map_id=canonical_map.id,
            decision_at=now - timedelta(minutes=5),
        )
        await AiCoordinator(
            [FakeProvider("openai", model="fixture-model", decision=_buy_decision(600.0))],
            timeout_seconds=1,
            virtual_bankroll=10_000.0,
        ).run_all(session, second)
        third = await _persist_fixture_snapshot(
            session,
            canonical_map_id=canonical_map.id,
            decision_at=now,
        )
        third_records = await AiCoordinator(
            [provider],
            timeout_seconds=1,
            virtual_bankroll=10_000.0,
            prior_decisions_limit=1,
        ).run_all(session, third)

    third_input = json.loads(provider.inputs[0])
    bankroll = third_input["virtual_bankroll"]
    # Both earlier stakes are deducted from the bankroll even though only the
    # latest round is shown to the model.
    assert bankroll["bankroll_before"] == 9_000.0
    assert bankroll["unsettled_stakes"] == 1_000.0
    assert len(third_input["prior_decisions"]) == 1
    assert third_input["prior_decisions"][0]["stake"] == 600.0
    assert third_input["prior_decisions"][0]["bankroll_before"] == 9_600.0
    assert third_records[0].bankroll_before == 9_000.0
    await engine.dispose()
