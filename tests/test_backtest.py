from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import Base
from app.evaluation.backtest import BacktestService, summarize_backtest_rows
from app.models import (
    AiDecisionRecord,
    CanonicalMap,
    CanonicalSeries,
    CanonicalTeam,
    DecisionFutureOdds,
    MapResultRecord,
)
from app.snapshots.repository import SnapshotRepository


def test_backtest_summary_keeps_experiment_versions_isolated() -> None:
    common = {
        "canonical_map_id": "map-1",
        "actual_winner": "A",
        "brier_score": 0.09,
        "log_loss": 0.357,
        "clv": 0.05,
    }
    rows = [
        {
            **common,
            "experiment": {
                "provider": "openai",
                "model": "model-x",
                "prompt_version": "prompt-v1",
                "decision_policy_version": "policy-v1",
                "ai_view_version": "ai-view-v2",
            },
            "action": "BUY_A",
            "fair_probability_a": 0.7,
            "result_correct": True,
            "unit_return": 1.0,
        },
        {
            **common,
            "canonical_map_id": "map-2",
            "experiment": {
                "provider": "openai",
                "model": "model-x",
                "prompt_version": "prompt-v1",
                "decision_policy_version": "policy-v1",
                "ai_view_version": "ai-view-v2",
            },
            "action": "BUY_B",
            "fair_probability_a": 0.6,
            "result_correct": False,
            "unit_return": -1.0,
        },
        {
            **common,
            "canonical_map_id": "map-3",
            "experiment": {
                "provider": "openai",
                "model": "model-x",
                "prompt_version": "prompt-v2",
                "decision_policy_version": "policy-v1",
                "ai_view_version": "ai-view-v3",
            },
            "action": "NO_BUY",
            "fair_probability_a": 0.8,
            "result_correct": None,
            "unit_return": None,
        },
    ]

    summaries = summarize_backtest_rows(rows, calibration_bins=5)

    assert len(summaries) == 2
    first = next(item for item in summaries if item["experiment"]["ai_view_version"] == "ai-view-v2")
    second = next(item for item in summaries if item["experiment"]["ai_view_version"] == "ai-view-v3")
    assert first["bet_count"] == 2
    assert first["wins"] == 1
    assert first["decision_level_roi"] == 0.0
    assert first["calibration"]["sample_count"] == 2
    assert second["bet_count"] == 0
    assert second["decision_level_roi"] is None
    assert second["action_counts"] == {"NO_BUY": 1}


@pytest.mark.asyncio
async def test_backtest_replays_snapshot_action_result_roi_calibration_and_clv() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    decision_at = datetime(2026, 8, 15, tzinfo=UTC)

    async with factory() as session, session.begin():
        team_a = CanonicalTeam(name="A")
        team_b = CanonicalTeam(name="B")
        session.add_all([team_a, team_b])
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
            decision_at=decision_at,
            mode="PREMATCH",
            identity={
                "team_a": {"id": str(team_a.id), "name": "A"},
                "team_b": {"id": str(team_b.id), "name": "B"},
            },
            market={
                "market_type": "Winner",
                "match_stage": "Map 1",
                # Deliberately reverse the observations: the backtest must map
                # prices by canonical team identity rather than array position.
                "observations": [
                    {"selection_team_id": str(team_b.id), "price": "2.20"},
                    {"selection_team_id": str(team_a.id), "price": "2.00"},
                ],
            },
            draft=None,
            history={},
            live=None,
            quality={"eligible": True},
        )
        decision_record = AiDecisionRecord(
            snapshot_id=snapshot.snapshot_id,
            snapshot_hash=snapshot.snapshot_hash,
            provider="openai",
            model="fixture-model",
            model_version="fixture-model",
            prompt_version="decision-analyst-v3",
            decision_policy_version="shadow-decision-v1",
            ai_view_version="ai-view-v3",
            ai_input_hash="a" * 64,
            request_started_at=decision_at,
            response_received_at=decision_at + timedelta(seconds=1),
            parse_status="SUCCESS",
            normalized_response={
                "action": "BUY_A",
                "fair_probability_a": 0.7,
                "confidence": 0.8,
                "market_assessment": "UNDERPRICED",
                "minimum_acceptable_odds_a": 1.8,
                "primary_reasons": ["fixture"],
                "counter_arguments": [],
                "data_quality_concerns": [],
                "blockers": [],
            },
        )
        session.add(decision_record)
        session.add(
            MapResultRecord(
                canonical_map_id=canonical_map.id,
                winner_team_id=team_a.id,
                basic_first_usable_at=decision_at + timedelta(hours=1),
                provider_conflict=False,
            )
        )
        session.add(
            DecisionFutureOdds(
                decision_snapshot_id=snapshot.snapshot_id,
                capture_type="CLOSING",
                horizon_seconds=None,
                triggered_at=decision_at + timedelta(minutes=45),
                due_at=decision_at + timedelta(minutes=45),
                observed_at=decision_at + timedelta(minutes=45),
                odds_a=Decimal("1.80"),
                odds_b=Decimal("2.30"),
                market_type="Winner",
                match_stage="Map 1",
                capture_policy_version="closing-policy-v1",
                pair_quality={"eligible": True},
                status="CAPTURED",
            )
        )
        await session.flush()

        report = await BacktestService().build_report(
            session,
            calibration_bins=5,
            include_snapshot_payload=True,
        )

    assert report["settled_row_count"] == 1
    row = report["rows"][0]
    assert row["snapshot_hash"] == snapshot.snapshot_hash
    assert row["ai_input_hash"] == "a" * 64
    assert row["market_price_mapping"] == "TEAM_ID"
    assert row["market_odds_a"] == 2.0
    assert row["market_odds_b"] == 2.2
    assert row["actual_winner"] == "A"
    assert row["unit_return"] == 1.0
    assert row["brier_score"] == pytest.approx(0.09)
    assert row["clv"] == pytest.approx(2.0 / 1.8 - 1.0)
    assert "snapshot_payload" in row

    experiment = report["experiments"][0]
    assert experiment["bet_count"] == 1
    assert experiment["wins"] == 1
    assert experiment["decision_level_roi"] == 1.0
    assert experiment["calibration"]["sample_count"] == 1
    assert experiment["calibration"]["expected_calibration_error"] == pytest.approx(0.3)
    await engine.dispose()
