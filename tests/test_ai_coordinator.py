import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.ai.base import (
    AI_VIEW_VERSION,
    DECISION_POLICY_VERSION,
    PROMPT_VERSION,
    AiProviderFailure,
    AiProviderResponse,
)
from app.ai.coordinator import AiCoordinator
from app.db import Base
from app.domain.decision import AiDecision
from app.models import AiDecisionRecord
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
    inputs: list[str] = field(default_factory=list)

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
            decision=_decision(),
            model_version=self.model,
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
        FakeProvider("ok"),
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
        # A legacy decision produced by the old ai-view-v1 semantics with the
        # SAME provider/model/prompt/policy must not block the v2 run.
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
                ai_view_version="ai-view-v1",
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
    assert record.ai_view_version == "ai-view-v2"
    assert record.ai_input_hash is not None and len(record.ai_input_hash) == 64

    # The fresh v2 record now dedupes the same experiment.
    async with factory() as session, session.begin():
        again = await AiCoordinator(
            [FakeProvider("openai", model="fixture-model")], timeout_seconds=1
        ).run_all(session, snapshot)
    assert again[0].id == record.id
    await engine.dispose()
