from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import Base
from app.domain.decision import AiDecision
from app.evaluation.metrics import METRICS_VERSION, EvaluationService
from app.models import (
    AiDecisionRecord,
    CanonicalMap,
    CanonicalSeries,
    CanonicalTeam,
    DecisionEvaluationRecord,
    MapResultRecord,
)
from app.snapshots.repository import SnapshotRepository


async def _settled_decision(
    session,
    *,
    action: str,
    stake: float | None,
    prices: tuple[str, str],
    winner_is_team_a: bool,
    metrics_version: str | None = None,
):
    team_a = CanonicalTeam(name="A")
    team_b = CanonicalTeam(name="B")
    session.add_all((team_a, team_b))
    await session.flush()
    series = CanonicalSeries(team_a_id=team_a.id, team_b_id=team_b.id)
    session.add(series)
    await session.flush()
    canonical_map = CanonicalMap(series_id=series.id, map_number=1)
    session.add(canonical_map)
    await session.flush()
    snapshot = await SnapshotRepository().persist(
        session,
        canonical_map_id=canonical_map.id,
        decision_at=datetime(2026, 1, 1, tzinfo=UTC),
        mode="PREMATCH",
        identity={
            "team_a": {"id": str(team_a.id), "name": "A"},
            "team_b": {"id": str(team_b.id), "name": "B"},
        },
        market={
            "market_type": "Winner",
            "match_stage": "Map 1",
            "observations": [
                {"selection_team_id": str(team_a.id), "price": prices[0]},
                {"selection_team_id": str(team_b.id), "price": prices[1]},
            ],
        },
        draft=None,
        history={},
        live=None,
        quality={"eligible": True},
    )
    decision = AiDecision(
        action=action,  # type: ignore[arg-type]
        fair_probability_a=0.5,
        confidence=0.6,
        market_assessment="FAIR",
        minimum_acceptable_odds_a=None,
        stake=stake,
        primary_reasons=["fixture"],
        counter_arguments=["fixture"],
        data_quality_concerns=[],
        blockers=[],
    )
    record = AiDecisionRecord(
        id=uuid4(),
        snapshot_id=snapshot.snapshot_id,
        snapshot_hash=snapshot.snapshot_hash,
        provider="openai",
        model="fixture-model",
        model_version="fixture-model",
        prompt_version="decision-analyst-v4",
        decision_policy_version="shadow-decision-v2",
        ai_view_version="ai-view-v4",
        request_started_at=snapshot.decision_at,
        parse_status="SUCCESS",
        normalized_response=decision.model_dump(mode="json"),
        bankroll_before=Decimal("1000.00"),
        stake=Decimal(str(stake)) if stake is not None else None,
    )
    session.add(record)
    session.add(
        MapResultRecord(
            canonical_map_id=canonical_map.id,
            winner_team_id=team_a.id if winner_is_team_a else team_b.id,
            basic_first_usable_at=snapshot.decision_at,
            settled_at=snapshot.decision_at,
        )
    )
    await session.flush()
    if metrics_version is not None:
        session.add(
            DecisionEvaluationRecord(
                ai_decision_id=record.id,
                result_correct=True,
                brier_score=0.0,
                log_loss=0.0,
                clv=0.0,
                future_odds_direction="FLAT",
                metrics_version=metrics_version,
            )
        )
        await session.flush()
    return snapshot, record


@pytest.mark.asyncio
async def test_virtual_pnl_settles_winning_buy_a_with_decision_time_odds() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session, session.begin():
        snapshot, record = await _settled_decision(
            session,
            action="BUY_A",
            stake=100.0,
            prices=("2.00", "3.00"),
            winner_is_team_a=True,
        )
        assert (
            await EvaluationService().evaluate_snapshot(session, snapshot_id=snapshot.snapshot_id)
            == 1
        )

    async with factory() as session:
        evaluation = await session.scalar(
            select(DecisionEvaluationRecord).where(
                DecisionEvaluationRecord.ai_decision_id == record.id
            )
        )
    assert evaluation is not None
    assert evaluation.metrics_version == METRICS_VERSION
    assert evaluation.virtual_pnl == Decimal("100.00")
    assert evaluation.virtual_odds == Decimal("2.00000")
    assert evaluation.unit_pnl == Decimal("1.00")
    await engine.dispose()


@pytest.mark.asyncio
async def test_virtual_pnl_settles_losing_buy_b_and_no_buy_zero() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session, session.begin():
        buy_snapshot, buy_record = await _settled_decision(
            session,
            action="BUY_B",
            stake=40.0,
            prices=("1.50", "2.50"),
            winner_is_team_a=True,
        )
        no_buy_snapshot, no_buy_record = await _settled_decision(
            session,
            action="NO_BUY",
            stake=None,
            prices=("1.50", "2.50"),
            winner_is_team_a=True,
        )
        await EvaluationService().evaluate_snapshot(session, snapshot_id=buy_snapshot.snapshot_id)
        await EvaluationService().evaluate_snapshot(
            session, snapshot_id=no_buy_snapshot.snapshot_id
        )

    async with factory() as session:
        buy = await session.scalar(
            select(DecisionEvaluationRecord).where(
                DecisionEvaluationRecord.ai_decision_id == buy_record.id
            )
        )
        no_buy = await session.scalar(
            select(DecisionEvaluationRecord).where(
                DecisionEvaluationRecord.ai_decision_id == no_buy_record.id
            )
        )
    assert buy is not None
    assert buy.virtual_pnl == Decimal("-40.00")
    assert buy.virtual_odds == Decimal("2.50000")
    assert buy.unit_pnl == Decimal("-1.00")
    assert no_buy is not None
    assert no_buy.virtual_pnl == Decimal("0.00")
    assert no_buy.unit_pnl is None
    assert no_buy.virtual_odds is None
    await engine.dispose()


@pytest.mark.asyncio
async def test_legacy_buy_without_stake_stays_unsettled_and_v1_row_is_backfilled() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session, session.begin():
        snapshot, record = await _settled_decision(
            session,
            action="BUY_A",
            stake=None,
            prices=("2.00", "3.00"),
            winner_is_team_a=True,
            metrics_version="decision-evaluation-v1",
        )
        assert (
            await EvaluationService().evaluate_snapshot(session, snapshot_id=snapshot.snapshot_id)
            == 1
        )

    async with factory() as session:
        evaluation = await session.scalar(
            select(DecisionEvaluationRecord).where(
                DecisionEvaluationRecord.ai_decision_id == record.id
            )
        )
    assert evaluation is not None
    assert evaluation.metrics_version == METRICS_VERSION
    assert evaluation.virtual_pnl is None
    assert evaluation.virtual_odds == Decimal("2.00000")
    assert evaluation.unit_pnl == Decimal("1.00")
    await engine.dispose()
