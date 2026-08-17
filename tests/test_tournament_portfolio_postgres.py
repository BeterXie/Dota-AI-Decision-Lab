import asyncio
import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.evaluation.portfolio import TournamentPortfolioService
from app.evaluation.portfolio_models import (
    TournamentPortfolioAccountRecord,
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


@pytest.mark.asyncio
async def test_postgres_serializes_competing_positions_against_one_event_cash_pool() -> None:
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url.startswith("postgresql"):
        pytest.skip("PostgreSQL row-lock regression requires DATABASE_URL")

    engine = create_async_engine(database_url, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    service = TournamentPortfolioService(initial_bankroll=10_000)
    now = datetime.now(UTC).replace(microsecond=0)
    experiment = ("concurrency", "fixture", "prompt", "policy", "view")

    async with factory() as session, session.begin():
        event = CanonicalEvent(name=f"Concurrent Cup {uuid4()}", started_at=now)
        team_a = CanonicalTeam(name=f"A-{uuid4()}")
        team_b = CanonicalTeam(name=f"B-{uuid4()}")
        session.add_all([event, team_a, team_b])
        await session.flush()
        series = CanonicalSeries(
            event_id=event.id,
            team_a_id=team_a.id,
            team_b_id=team_b.id,
            best_of=3,
            scheduled_at=now,
        )
        session.add(series)
        await session.flush()
        maps = [
            CanonicalMap(series_id=series.id, map_number=1, scheduled_at=now),
            CanonicalMap(
                series_id=series.id,
                map_number=2,
                scheduled_at=now + timedelta(minutes=5),
            ),
        ]
        session.add_all(maps)
        await session.flush()
        snapshots = []
        for index, canonical_map in enumerate(maps, start=1):
            snapshot = DecisionSnapshotRecord(
                id=uuid4(),
                canonical_map_id=canonical_map.id,
                decision_at=now + timedelta(minutes=index),
                created_at=now + timedelta(minutes=index),
                mode="LIVE_BASIC",
                canonical_payload={
                    "identity": {
                        "team_a": {"id": str(team_a.id)},
                        "team_b": {"id": str(team_b.id)},
                    },
                    "market": {
                        "observations": [
                            {"selection_team_id": str(team_a.id), "price": "1.90"},
                            {"selection_team_id": str(team_b.id), "price": "2.10"},
                        ]
                    },
                },
                snapshot_hash=f"concurrency-{uuid4()}",
            )
            session.add(snapshot)
            snapshots.append(snapshot)
        await session.flush()
        await service.context_for_snapshot(
            session,
            snapshot_id=snapshots[0].id,
            experiment=experiment,
        )
        decisions = []
        for index, snapshot in enumerate(snapshots):
            record = _decision(
                snapshot,
                experiment=experiment,
                stake=7000,
                offset=index,
            )
            session.add(record)
            decisions.append(record)
        await session.flush()
        event_id = event.id
        decision_ids = [item.id for item in decisions]

    async def place(decision_id):
        async with factory() as session, session.begin():
            decision = await session.get(AiDecisionRecord, decision_id)
            assert decision is not None
            position = await service.record_decision_position(session, decision)
            assert position is not None
            return position.id

    await asyncio.gather(*(place(item) for item in decision_ids))

    async with factory() as session:
        account = await session.scalar(
            select(TournamentPortfolioAccountRecord).where(
                TournamentPortfolioAccountRecord.canonical_event_id == event_id,
                TournamentPortfolioAccountRecord.provider == experiment[0],
                TournamentPortfolioAccountRecord.model == experiment[1],
            )
        )
        assert account is not None
        positions = list(
            (
                await session.scalars(
                    select(TournamentPortfolioPositionRecord).where(
                        TournamentPortfolioPositionRecord.portfolio_account_id == account.id
                    )
                )
            ).all()
        )
        assert sorted(item.status for item in positions) == ["OPEN", "REJECTED"]
        assert account.cash_balance == Decimal("3000.00")
        assert account.locked_balance == Decimal("7000.00")
        assert account.cash_balance + account.locked_balance == Decimal("10000.00")

    await engine.dispose()


def _decision(snapshot, *, experiment, stake: float, offset: int) -> AiDecisionRecord:
    provider, model, prompt, policy, view = experiment
    return AiDecisionRecord(
        snapshot_id=snapshot.id,
        snapshot_hash=snapshot.snapshot_hash,
        provider=provider,
        model=model,
        model_version=model,
        prompt_version=prompt,
        decision_policy_version=policy,
        ai_view_version=view,
        ai_input_hash=f"concurrency-{uuid4()}",
        bankroll_before=Decimal("10000.00"),
        stake=Decimal(str(stake)),
        request_started_at=snapshot.decision_at + timedelta(seconds=offset),
        response_received_at=snapshot.decision_at + timedelta(seconds=offset + 1),
        latency_seconds=1.0,
        normalized_response={
            "action": "BUY_A",
            "fair_probability_a": 0.6,
            "confidence": 0.7,
            "market_assessment": "UNDERPRICED",
            "minimum_acceptable_odds_a": 1.7,
            "stake": stake,
            "primary_reasons": ["concurrency fixture"],
            "blockers": [],
        },
        raw_response={"fixture": True},
        parse_status="SUCCESS",
    )


@pytest.mark.asyncio
async def test_postgres_same_decision_position_creation_is_idempotent() -> None:
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url.startswith("postgresql"):
        pytest.skip("PostgreSQL row-lock regression requires DATABASE_URL")

    engine = create_async_engine(database_url, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    service = TournamentPortfolioService(initial_bankroll=10_000)
    now = datetime.now(UTC).replace(microsecond=0)
    experiment = ("idempotent", "fixture", "prompt", "policy", "view")

    async with factory() as session, session.begin():
        event = CanonicalEvent(name=f"Idempotent Cup {uuid4()}", started_at=now)
        team_a = CanonicalTeam(name=f"A-{uuid4()}")
        team_b = CanonicalTeam(name=f"B-{uuid4()}")
        session.add_all([event, team_a, team_b])
        await session.flush()
        series = CanonicalSeries(
            event_id=event.id,
            team_a_id=team_a.id,
            team_b_id=team_b.id,
            best_of=1,
            scheduled_at=now,
        )
        session.add(series)
        await session.flush()
        canonical_map = CanonicalMap(series_id=series.id, map_number=1, scheduled_at=now)
        session.add(canonical_map)
        await session.flush()
        snapshot = DecisionSnapshotRecord(
            id=uuid4(),
            canonical_map_id=canonical_map.id,
            decision_at=now + timedelta(minutes=1),
            created_at=now + timedelta(minutes=1),
            mode="LIVE_BASIC",
            canonical_payload={
                "identity": {
                    "team_a": {"id": str(team_a.id)},
                    "team_b": {"id": str(team_b.id)},
                },
                "market": {
                    "observations": [
                        {"selection_team_id": str(team_a.id), "price": "1.90"},
                        {"selection_team_id": str(team_b.id), "price": "2.10"},
                    ]
                },
            },
            snapshot_hash=f"idempotent-{uuid4()}",
        )
        session.add(snapshot)
        await session.flush()
        decision = _decision(snapshot, experiment=experiment, stake=1000, offset=0)
        session.add(decision)
        await session.flush()
        await service.context_for_snapshot(
            session,
            snapshot_id=snapshot.id,
            experiment=experiment,
        )
        event_id = event.id
        decision_id = decision.id

    async def place():
        async with factory() as session, session.begin():
            decision = await session.get(AiDecisionRecord, decision_id)
            assert decision is not None
            position = await service.record_decision_position(session, decision)
            assert position is not None
            return position.id

    first, second = await asyncio.gather(place(), place())
    assert first == second

    async with factory() as session:
        account = await session.scalar(
            select(TournamentPortfolioAccountRecord).where(
                TournamentPortfolioAccountRecord.canonical_event_id == event_id,
                TournamentPortfolioAccountRecord.provider == experiment[0],
            )
        )
        assert account is not None
        positions = list(
            (
                await session.scalars(
                    select(TournamentPortfolioPositionRecord).where(
                        TournamentPortfolioPositionRecord.portfolio_account_id == account.id
                    )
                )
            ).all()
        )
        assert len(positions) == 1
        assert positions[0].cash_before == Decimal("10000.00")
        assert account.cash_balance == Decimal("9000.00")
        assert account.locked_balance == Decimal("1000.00")

    await engine.dispose()
