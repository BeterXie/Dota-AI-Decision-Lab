from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import Base
from app.evaluation import EvaluationService, SettlementService, TournamentPortfolioService
from app.evaluation.quality import QualityGatePolicy, TournamentQualityService
from app.models import (
    AiDecisionRecord,
    CanonicalEvent,
    CanonicalMap,
    CanonicalSeries,
    CanonicalTeam,
    DecisionEvaluationRecord,
    DecisionFutureOdds,
    DecisionSnapshotRecord,
)

NOW = datetime(2026, 8, 17, 10, 30, tzinfo=UTC)
EXPERIMENT = ("quality", "fixture", "prompt-v1", "policy-v1", "view-v1")


@pytest.mark.asyncio
async def test_quality_report_combines_portfolio_calibration_and_market_baseline() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    portfolio = TournamentPortfolioService(initial_bankroll=10_000)
    quality = TournamentQualityService(
        portfolio,
        policy=QualityGatePolicy(
            min_settled_maps=2,
            min_settled_bets=2,
            min_prediction_samples=2,
            min_roi=0.0,
            min_average_clv=0.0,
            min_brier_improvement_vs_market=0.0,
            max_drawdown_pct=0.30,
        ),
    )

    async with factory() as session, session.begin():
        event = CanonicalEvent(name="Quality Cup", started_at=NOW)
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

        current_bankroll = Decimal("10000.00")
        for index in (1, 2):
            canonical_map = CanonicalMap(
                series_id=series.id,
                map_number=index,
                scheduled_at=NOW + timedelta(minutes=index * 30),
            )
            session.add(canonical_map)
            await session.flush()
            snapshot = DecisionSnapshotRecord(
                id=uuid4(),
                canonical_map_id=canonical_map.id,
                decision_at=NOW + timedelta(minutes=index * 30 + 1),
                created_at=NOW + timedelta(minutes=index * 30 + 1),
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
                snapshot_hash=f"quality-{index}-{uuid4()}",
            )
            session.add(snapshot)
            await session.flush()
            decision = _decision(snapshot, bankroll=current_bankroll, index=index)
            session.add(decision)
            await session.flush()
            position = await portfolio.record_decision_position(session, decision)
            assert position is not None and position.status == "OPEN"
            observed_at = NOW + timedelta(minutes=index * 30 + 25)
            result = await SettlementService().settle(
                session,
                canonical_map_id=canonical_map.id,
                winner_team_id=team_a.id,
                provider="fixture",
                provider_match_id=f"quality-{index}",
                result_observed_at=observed_at,
                basic_first_usable_at=observed_at,
                raw_event_id=uuid4(),
                normalizer_version="quality-v1",
                identity_confidence=1.0,
            )
            # Keep the ledger timeline deterministic: this replayed settlement
            # happened at the recorded provider observation, not wall-clock test time.
            result.settled_at = observed_at
            await portfolio.settle_map(
                session,
                canonical_map_id=canonical_map.id,
                winner_team_id=result.winner_team_id,
                provider_conflict=result.provider_conflict,
                settled_at=result.settled_at,
            )
            assert (
                await EvaluationService().evaluate_snapshot(
                    session,
                    snapshot_id=snapshot.id,
                )
                == 1
            )
            evaluation = await session.scalar(
                select(DecisionEvaluationRecord).where(
                    DecisionEvaluationRecord.ai_decision_id == decision.id
                )
            )
            assert evaluation is not None
            evaluation.clv = 0.02
            session.add(
                DecisionFutureOdds(
                    decision_snapshot_id=snapshot.id,
                    capture_type="TIME_HORIZON",
                    horizon_seconds=30,
                    triggered_at=snapshot.decision_at,
                    due_at=snapshot.decision_at + timedelta(seconds=30),
                    observed_at=decision.response_received_at + timedelta(seconds=30),
                    odds_a=Decimal("1.80"),
                    odds_b=Decimal("2.20"),
                    market_type="match_winner",
                    match_stage=f"Map {index}",
                    market_status="READY",
                    capture_policy_version="quality-test-v1",
                    pair_quality={"eligible": True},
                    pair_skew_seconds=0.0,
                    status="CAPTURED",
                )
            )
            if index == 1:
                extra_snapshot = DecisionSnapshotRecord(
                    id=uuid4(),
                    canonical_map_id=canonical_map.id,
                    decision_at=snapshot.decision_at + timedelta(minutes=5),
                    created_at=snapshot.decision_at + timedelta(minutes=5),
                    mode="LIVE_BASIC",
                    canonical_payload=snapshot.canonical_payload,
                    snapshot_hash=f"quality-extra-{uuid4()}",
                )
                session.add(extra_snapshot)
                await session.flush()
                extra_decision = _no_buy_decision(extra_snapshot)
                session.add(extra_decision)
                await session.flush()
                assert (
                    await EvaluationService().evaluate_snapshot(
                        session,
                        snapshot_id=extra_snapshot.id,
                    )
                    == 1
                )
            current_bankroll += Decimal("900.00")

        report = await quality.build_report(session, canonical_event_id=event.id)
        assert report["gate_mode"] == "SHADOW_ONLY"
        assert len(report["experiments"]) == 1
        experiment = report["experiments"][0]
        assert experiment["portfolio"]["cash_balance"] == 11800.0
        assert experiment["portfolio"]["roi"] == pytest.approx(0.18)
        assert experiment["quality"]["settled_maps"] == 2
        assert experiment["quality"]["successful_decisions"] == 3
        assert experiment["quality"]["prediction_sample_count"] == 2
        assert experiment["quality"]["decision_level"]["prediction_sample_count"] == 3
        assert experiment["quality"]["sample_policy"]["portfolio"] == "ALL_EXECUTED_POSITIONS"
        assert experiment["quality"]["average_clv"] == pytest.approx(0.02)
        comparison = experiment["quality"]["market_comparison"]
        assert comparison["sample_count"] == 2
        assert comparison["brier_improvement_vs_market"] > 0
        assert experiment["gate"] == {
            "mode": "SHADOW_ONLY",
            "status": "PASS",
            "failures": [],
        }
        latency = experiment["execution_latency"]
        assert latency["position_policy"] == "FIRST_SETTLED_POSITION_PER_MAP"
        horizon = latency["horizons"]["30"]
        assert horizon["sample_count"] == 2
        assert horizon["actionable_rate"] == 1.0
        assert horizon["average_model_edge_vs_break_even"] == pytest.approx(0.60 - (1.0 / 1.80))
        assert horizon["average_odds_slippage_pct"] == pytest.approx((1.80 / 1.90) - 1.0)
        assert horizon["average_observed_after_ai_seconds"] == pytest.approx(30.0)
        assert experiment["equity_curve"][0]["entry_type"] == "EVENT_FUNDED"
        assert experiment["equity_curve"][-1]["equity"] == 11800.0

    await engine.dispose()


def _decision(
    snapshot: DecisionSnapshotRecord,
    *,
    bankroll: Decimal,
    index: int,
) -> AiDecisionRecord:
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
        ai_input_hash=f"quality-input-{index}-{uuid4()}",
        bankroll_before=bankroll,
        stake=Decimal("1000.00"),
        request_started_at=snapshot.decision_at,
        response_received_at=snapshot.decision_at + timedelta(seconds=1),
        latency_seconds=1.0,
        normalized_response={
            "action": "BUY_A",
            "fair_probability_a": 0.60,
            "confidence": 0.75,
            "market_assessment": "UNDERPRICED",
            "minimum_acceptable_odds_a": 1.70,
            "stake": 1000,
            "primary_reasons": ["quality fixture"],
            "blockers": [],
        },
        raw_response={"fixture": True},
        parse_status="SUCCESS",
    )


def _no_buy_decision(snapshot: DecisionSnapshotRecord) -> AiDecisionRecord:
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
        ai_input_hash=f"quality-no-buy-{uuid4()}",
        bankroll_before=Decimal("10900.00"),
        stake=None,
        request_started_at=snapshot.decision_at,
        response_received_at=snapshot.decision_at + timedelta(seconds=1),
        latency_seconds=1.0,
        normalized_response={
            "action": "NO_BUY",
            "fair_probability_a": 0.62,
            "confidence": 0.65,
            "market_assessment": "FAIR",
            "minimum_acceptable_odds_a": None,
            "stake": None,
            "primary_reasons": ["repeated checkpoint fixture"],
            "blockers": [],
        },
        raw_response={"fixture": True},
        parse_status="SUCCESS",
    )
