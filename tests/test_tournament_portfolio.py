from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import Base
from app.evaluation.portfolio import TournamentPortfolioService
from app.evaluation.portfolio_models import (
    TournamentPortfolioAccountRecord,
    TournamentPortfolioLedgerRecord,
    TournamentPortfolioPositionRecord,
)
from app.models import (
    AiDecisionRecord,
    CanonicalEvent,
    CanonicalMap,
    CanonicalSeries,
    CanonicalTeam,
    DecisionSnapshotRecord,
)

NOW = datetime(2026, 8, 17, 9, 30, tzinfo=UTC)
EXPERIMENT = ("gpt", "fixture", "prompt-v1", "policy-v1", "view-v1")


async def _fixture(session):
    event = CanonicalEvent(name="TI Shadow Cup", started_at=NOW)
    team_a = CanonicalTeam(name="Radiant")
    team_b = CanonicalTeam(name="Dire")
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
    map1 = CanonicalMap(series_id=series.id, map_number=1, scheduled_at=NOW)
    map2 = CanonicalMap(
        series_id=series.id,
        map_number=2,
        scheduled_at=NOW + timedelta(hours=1),
    )
    session.add_all([map1, map2])
    await session.flush()
    snapshot1 = _snapshot(map1.id, team_a.id, team_b.id, 1)
    snapshot2 = _snapshot(map2.id, team_a.id, team_b.id, 2)
    session.add_all([snapshot1, snapshot2])
    await session.flush()
    return event, team_a, team_b, series, map1, map2, snapshot1, snapshot2


def _snapshot(map_id, team_a_id, team_b_id, index):
    return DecisionSnapshotRecord(
        id=uuid4(),
        canonical_map_id=map_id,
        decision_at=NOW + timedelta(minutes=index),
        created_at=NOW + timedelta(minutes=index),
        mode="LIVE_BASIC",
        canonical_payload={
            "identity": {
                "team_a": {"id": str(team_a_id)},
                "team_b": {"id": str(team_b_id)},
            },
            "market": {
                "observations": [
                    {"selection_team_id": str(team_a_id), "price": "1.90"},
                    {"selection_team_id": str(team_b_id), "price": "2.10"},
                ]
            },
        },
        snapshot_hash=f"portfolio-snapshot-{index}",
    )


def _decision(snapshot, *, action: str, stake: float, offset: int = 0):
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
        ai_input_hash=f"hash-{snapshot.id}-{offset}",
        bankroll_before=Decimal("10000.00"),
        stake=Decimal(str(stake)),
        request_started_at=snapshot.decision_at + timedelta(seconds=offset),
        response_received_at=snapshot.decision_at + timedelta(seconds=offset + 1),
        latency_seconds=1.0,
        normalized_response={
            "action": action,
            "fair_probability_a": 0.6,
            "confidence": 0.7,
            "market_assessment": "UNDERPRICED",
            "minimum_acceptable_odds_a": 1.7,
            "stake": stake,
            "primary_reasons": ["fixture"],
            "blockers": [],
        },
        raw_response={"fixture": True},
        parse_status="SUCCESS",
    )


@pytest.mark.asyncio
async def test_event_bankroll_carries_profit_and_loss_across_maps() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    service = TournamentPortfolioService(initial_bankroll=10_000)

    async with factory() as session, session.begin():
        event, team_a, _, _, map1, map2, snapshot1, snapshot2 = await _fixture(session)
        before = await service.context_for_snapshot(
            session,
            snapshot_id=snapshot1.id,
            experiment=EXPERIMENT,
        )
        assert before is not None
        assert before.cash_balance == Decimal("10000.00")

        first = _decision(snapshot1, action="BUY_A", stake=1000)
        session.add(first)
        await session.flush()
        await service.record_decision_position(session, first)
        await service.settle_map(
            session,
            canonical_map_id=map1.id,
            winner_team_id=team_a.id,
            provider_conflict=False,
        )
        after_win = await service.context_for_snapshot(
            session,
            snapshot_id=snapshot2.id,
            experiment=EXPERIMENT,
        )
        assert after_win is not None
        assert after_win.cash_balance == Decimal("10900.00")

        second = _decision(snapshot2, action="BUY_B", stake=2000)
        second.bankroll_before = after_win.cash_balance
        session.add(second)
        await session.flush()
        await service.record_decision_position(session, second)
        await service.settle_map(
            session,
            canonical_map_id=map2.id,
            winner_team_id=team_a.id,
            provider_conflict=False,
        )

        leaderboard = await service.leaderboard(session, canonical_event_id=event.id)
        assert len(leaderboard) == 1
        row = leaderboard[0]
        assert row["cash_balance"] == 8900.0
        assert row["realized_pnl"] == -1100.0
        assert row["roi"] == pytest.approx(-0.11)
        assert row["wins"] == 1
        assert row["losses"] == 1
        assert row["max_drawdown"] == 2000.0

    await engine.dispose()


@pytest.mark.asyncio
async def test_open_positions_share_one_event_cash_pool() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    service = TournamentPortfolioService(initial_bankroll=10_000)

    async with factory() as session, session.begin():
        event, _, _, _, _, _, snapshot1, snapshot2 = await _fixture(session)
        first = _decision(snapshot1, action="BUY_A", stake=7000)
        session.add(first)
        await session.flush()
        position1 = await service.record_decision_position(session, first)
        assert position1 is not None and position1.status == "OPEN"
        assert position1.opened_at == first.response_received_at
        placed_at = await session.scalar(
            select(TournamentPortfolioLedgerRecord.occurred_at).where(
                TournamentPortfolioLedgerRecord.position_id == position1.id,
                TournamentPortfolioLedgerRecord.entry_type == "BET_PLACED",
            )
        )
        assert placed_at.replace(tzinfo=UTC) == first.response_received_at

        second = _decision(snapshot2, action="BUY_B", stake=4000)
        session.add(second)
        await session.flush()
        position2 = await service.record_decision_position(session, second)
        assert position2 is not None
        assert position2.status == "REJECTED"
        assert position2.rejection_reason == "INSUFFICIENT_CASH"

        account = await session.scalar(
            select(TournamentPortfolioAccountRecord).where(
                TournamentPortfolioAccountRecord.canonical_event_id == event.id
            )
        )
        assert account is not None
        assert account.cash_balance == Decimal("3000.00")
        assert account.locked_balance == Decimal("7000.00")
        assert account.cash_balance + account.locked_balance == Decimal("10000.00")

    await engine.dispose()


@pytest.mark.asyncio
async def test_void_result_returns_locked_capital_without_profit() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    service = TournamentPortfolioService(initial_bankroll=10_000)

    async with factory() as session, session.begin():
        event, _, _, _, map1, _, snapshot1, _ = await _fixture(session)
        decision = _decision(snapshot1, action="BUY_A", stake=2500)
        session.add(decision)
        await session.flush()
        position = await service.record_decision_position(session, decision)
        assert position is not None and position.status == "OPEN"
        await service.settle_map(
            session,
            canonical_map_id=map1.id,
            winner_team_id=None,
            provider_conflict=True,
        )

        account = await session.scalar(
            select(TournamentPortfolioAccountRecord).where(
                TournamentPortfolioAccountRecord.canonical_event_id == event.id
            )
        )
        assert account is not None
        assert account.cash_balance == Decimal("10000.00")
        assert account.locked_balance == Decimal("0.00")
        assert account.realized_pnl == Decimal("0.00")
        position = await session.get(TournamentPortfolioPositionRecord, position.id)
        assert position is not None and position.status == "VOID"
        entries = list(
            (
                await session.scalars(
                    select(TournamentPortfolioLedgerRecord.entry_type).order_by(
                        TournamentPortfolioLedgerRecord.occurred_at
                    )
                )
            ).all()
        )
        assert entries == ["EVENT_FUNDED", "BET_PLACED", "BET_VOID"]

    await engine.dispose()


@pytest.mark.asyncio
async def test_unknown_winner_identity_voids_positions() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    service = TournamentPortfolioService(initial_bankroll=10_000)

    async with factory() as session, session.begin():
        event, _, _, _, map1, _, snapshot1, _ = await _fixture(session)
        outsider = CanonicalTeam(name="Outsider")
        session.add(outsider)
        await session.flush()
        decision = _decision(snapshot1, action="BUY_A", stake=2500)
        session.add(decision)
        await session.flush()
        position = await service.record_decision_position(session, decision)
        assert position is not None and position.status == "OPEN"
        await service.settle_map(
            session,
            canonical_map_id=map1.id,
            winner_team_id=outsider.id,
            provider_conflict=False,
        )
        assert position.status == "VOID"
        account = await session.scalar(
            select(TournamentPortfolioAccountRecord).where(
                TournamentPortfolioAccountRecord.canonical_event_id == event.id
            )
        )
        assert account is not None
        assert account.cash_balance == Decimal("10000.00")
        assert account.realized_pnl == Decimal("0.00")

    await engine.dispose()
