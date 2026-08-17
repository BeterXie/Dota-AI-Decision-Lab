import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.ai.base import AiProviderResponse
from app.ai.coordinator import AiCoordinator
from app.db import Base
from app.domain.decision import AiDecision
from app.evaluation.portfolio import TournamentPortfolioService
from app.models import CanonicalMap, CanonicalSeries, CanonicalTeam
from app.snapshots.repository import SnapshotRepository


@dataclass
class _Provider:
    name: str = "unresolved-event"
    model: str = "fixture"
    inputs: list[str] = field(default_factory=list)

    async def decide(self, snapshot_input: str) -> AiProviderResponse:
        self.inputs.append(snapshot_input)
        return AiProviderResponse(
            raw_response={"fixture": True},
            decision=AiDecision(
                action="NO_BUY",
                fair_probability_a=None,
                confidence=0.2,
                market_assessment="UNKNOWN",
                minimum_acceptable_odds_a=None,
                stake=None,
                primary_reasons=["event identity unresolved"],
                blockers=["EVENT_IDENTITY_UNRESOLVED"],
            ),
            model_version=self.model,
        )

    async def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_enabled_portfolio_does_not_fall_back_to_per_map_bankroll_without_event() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    provider = _Provider()

    async with factory() as session, session.begin():
        team_a = CanonicalTeam(id=uuid4(), name="A")
        team_b = CanonicalTeam(id=uuid4(), name="B")
        session.add_all([team_a, team_b])
        await session.flush()
        series = CanonicalSeries(
            id=uuid4(),
            event_id=None,
            team_a_id=team_a.id,
            team_b_id=team_b.id,
            best_of=3,
        )
        session.add(series)
        await session.flush()
        canonical_map = CanonicalMap(id=uuid4(), series_id=series.id, map_number=1)
        session.add(canonical_map)
        await session.flush()
        snapshot = await SnapshotRepository().persist(
            session,
            canonical_map_id=canonical_map.id,
            decision_at=datetime(2026, 8, 17, 13, 0, tzinfo=UTC),
            mode="LIVE_BASIC",
            identity={
                "event_id": None,
                "series_id": str(series.id),
                "map_id": str(canonical_map.id),
                "team_a": {"id": str(team_a.id), "name": "A"},
                "team_b": {"id": str(team_b.id), "name": "B"},
            },
            market={
                "observations": [
                    {"selection_team_id": str(team_a.id), "price": "1.90"},
                    {"selection_team_id": str(team_b.id), "price": "2.10"},
                ]
            },
            draft=None,
            history={},
            live=None,
            quality={"eligible": True, "blockers": [], "warnings": []},
        )
        records = await AiCoordinator(
            [provider],
            timeout_seconds=1,
            virtual_bankroll=10_000,
            portfolio=TournamentPortfolioService(initial_bankroll=10_000),
        ).run_all(session, snapshot)

    assert len(records) == 1
    assert records[0].parse_status == "SUCCESS"
    assert records[0].bankroll_before == 0.0
    payload = json.loads(provider.inputs[0])
    assert payload["virtual_bankroll"]["scope"] == "UNRESOLVED_CANONICAL_EVENT"
    assert payload["virtual_bankroll"]["bankroll_before"] == 0.0
    assert payload["virtual_bankroll"]["reason"] == "EVENT_IDENTITY_UNRESOLVED"
    await engine.dispose()
