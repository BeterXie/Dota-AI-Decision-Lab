import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.ai.base import AiProviderFailure, AiProviderResponse
from app.ai.coordinator import AiCoordinator
from app.db import Base
from app.domain.decision import AiDecision
from app.snapshots.repository import SnapshotRepository


def _decision() -> AiDecision:
    return AiDecision(
        action="NO_BUY",
        fair_probability_a=None,
        confidence=0.5,
        market_assessment="UNKNOWN",
        max_acceptable_price=None,
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
