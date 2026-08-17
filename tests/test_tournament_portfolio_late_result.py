from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import Base
from app.evaluation import SettlementService
from app.evaluation.portfolio import TournamentPortfolioService
from app.evaluation.portfolio_models import TournamentPortfolioAccountRecord
from app.models import (
    AiDecisionRecord,
    CanonicalEvent,
    CanonicalMap,
    CanonicalSeries,
    CanonicalTeam,
    DecisionSnapshotRecord,
)

NOW = datetime(2026, 8, 17, 10, 0, tzinfo=UTC)
EXPERIMENT = ("late", "fixture", "prompt", "policy", "view")


@pytest.mark.asyncio
async def test_ai_response_after_map_settlement_is_rejected() -> None:
    engine, factory = await _database()
    service = TournamentPortfolioService(initial_bankroll=10_000)
    async with factory() as session, session.begin():
        event, team_a, map1, snapshot = await _fixture(session)
        decision = _decision(snapshot)
        session.add(decision)
        await session.flush()
        result = await _result(session, map1.id, team_a.id, decision.response_received_at)
        result.settled_at = decision.response_received_at - timedelta(seconds=1)

        position = await service.record_decision_position(session, decision)
        assert position is not None
        assert position.status == "REJECTED"
        assert position.rejection_reason == "MAP_ALREADY_SETTLED"
        account = await session.scalar(
            select(TournamentPortfolioAccountRecord).where(
                TournamentPortfolioAccountRecord.canonical_event_id == event.id
            )
        )
        assert account is not None
        assert account.cash_balance == Decimal("10000.00")
        assert account.locked_balance == Decimal("0.00")
    await engine.dispose()


@pytest.mark.asyncio
async def test_pre_result_response_persisted_late_is_immediately_settled() -> None:
    engine, factory = await _database()
    service = TournamentPortfolioService(initial_bankroll=10_000)
    async with factory() as session, session.begin():
        event, team_a, map1, snapshot = await _fixture(session)
        decision = _decision(snapshot)
        session.add(decision)
        await session.flush()
        result = await _result(
            session,
            map1.id,
            team_a.id,
            decision.response_received_at + timedelta(seconds=10),
        )
        result.settled_at = decision.response_received_at + timedelta(seconds=10)

        position = await service.record_decision_position(session, decision)
        assert position is not None
        assert position.status == "WON"
        assert position.payout == Decimal("1900.00")
        account = await session.scalar(
            select(TournamentPortfolioAccountRecord).where(
                TournamentPortfolioAccountRecord.canonical_event_id == event.id
            )
        )
        assert account is not None
        assert account.cash_balance == Decimal("10900.00")
        assert account.locked_balance == Decimal("0.00")
        assert account.realized_pnl == Decimal("900.00")
    await engine.dispose()


async def _database():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _fixture(session):
    event = CanonicalEvent(name="Late Result Cup", started_at=NOW)
    team_a = CanonicalTeam(name="A")
    team_b = CanonicalTeam(name="B")
    session.add_all([event, team_a, team_b])
    await session.flush()
    series = CanonicalSeries(
        event_id=event.id,
        team_a_id=team_a.id,
        team_b_id=team_b.id,
        best_of=3,
        scheduled_at=NOW,
    )
    session.add(series)
    await session.flush()
    canonical_map = CanonicalMap(series_id=series.id, map_number=1, scheduled_at=NOW)
    session.add(canonical_map)
    await session.flush()
    snapshot = DecisionSnapshotRecord(
        id=uuid4(),
        canonical_map_id=canonical_map.id,
        decision_at=NOW + timedelta(minutes=1),
        created_at=NOW + timedelta(minutes=1),
        mode="LIVE_BASIC",
        canonical_payload={
            "quality": {"eligible": True, "blockers": [], "warnings": []},
            "identity": {
                "team_a": {"id": str(team_a.id)},
                "team_b": {"id": str(team_b.id)},
            },
            "market": {
                "quality": {"eligible": True, "blockers": [], "warnings": []},
                "observations": [
                    {"selection_team_id": str(team_a.id), "price": "1.90"},
                    {"selection_team_id": str(team_b.id), "price": "2.10"},
                ],
            },
        },
        snapshot_hash=f"late-{uuid4()}",
    )
    session.add(snapshot)
    await session.flush()
    return event, team_a, canonical_map, snapshot


def _decision(snapshot):
    provider, model, prompt, policy, view = EXPERIMENT
    return AiDecisionRecord(
        snapshot_id=snapshot.id,
        snapshot_hash=snapshot.snapshot_hash,
        provider=provider,
        model=model,
        model_version=model,
        prompt_version=prompt,
        decision_policy_version=policy,
        ai_view_version=view,
        ai_input_hash=f"late-input-{uuid4()}",
        bankroll_before=Decimal("10000.00"),
        stake=Decimal("1000.00"),
        request_started_at=snapshot.decision_at,
        response_received_at=snapshot.decision_at + timedelta(seconds=2),
        latency_seconds=2.0,
        normalized_response={
            "action": "BUY_A",
            "fair_probability_a": 0.6,
            "confidence": 0.7,
            "market_assessment": "UNDERPRICED",
            "minimum_acceptable_odds_a": 1.7,
            "stake": 1000,
            "primary_reasons": ["late result fixture"],
            "blockers": [],
        },
        raw_response={"fixture": True},
        parse_status="SUCCESS",
    )


async def _result(session, canonical_map_id, winner_team_id, observed_at):
    return await SettlementService().settle(
        session,
        canonical_map_id=canonical_map_id,
        winner_team_id=winner_team_id,
        provider="fixture",
        provider_match_id=f"late-{uuid4()}",
        result_observed_at=observed_at,
        basic_first_usable_at=observed_at,
        raw_event_id=uuid4(),
        normalizer_version="portfolio-v1",
        identity_confidence=1.0,
    )
