from datetime import UTC, datetime, timedelta
from math import log
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import Base
from app.evaluation.benchmark import (
    BASELINE_AI_VIEW_VERSION,
    BASELINE_DECISION_POLICY_VERSION,
    BASELINE_FROZEN_AT_COMMIT,
    BASELINE_ID,
    BASELINE_PROMPT_VERSION,
    AiBaselineBenchmarkService,
)
from app.models import (
    AiDecisionRecord,
    CanonicalEvent,
    CanonicalMap,
    CanonicalSeries,
    CanonicalTeam,
    DecisionEvaluationRecord,
    DecisionSnapshotRecord,
    MapResultRecord,
)

NOW = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)
BASELINE = (
    "openai",
    "gpt-5.6-terra",
    BASELINE_PROMPT_VERSION,
    BASELINE_DECISION_POLICY_VERSION,
    BASELINE_AI_VIEW_VERSION,
)
CHALLENGER = (
    "openai",
    "gpt-5.6-terra",
    "decision-analyst-vNext-test",
    BASELINE_DECISION_POLICY_VERSION,
    BASELINE_AI_VIEW_VERSION,
)


@pytest.mark.asyncio
async def test_benchmark_freezes_baseline_and_compares_first_forecast_per_map() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session, session.begin():
        event = CanonicalEvent(name="Benchmark Cup", started_at=NOW)
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

        outcomes = [True, False]
        baseline_probabilities = [0.8, 0.7]
        challenger_probabilities = [0.9, 0.4]
        for index, team_a_won in enumerate(outcomes, start=1):
            canonical_map = CanonicalMap(
                series_id=series.id,
                map_number=index,
                scheduled_at=NOW + timedelta(minutes=30 * index),
            )
            session.add(canonical_map)
            await session.flush()
            snapshot = DecisionSnapshotRecord(
                id=uuid4(),
                canonical_map_id=canonical_map.id,
                decision_at=NOW + timedelta(minutes=30 * index, seconds=10),
                created_at=NOW + timedelta(minutes=30 * index, seconds=10),
                mode="LIVE_BASIC",
                canonical_payload={
                    "identity": {
                        "team_a": {"id": str(team_a.id)},
                        "team_b": {"id": str(team_b.id)},
                    },
                    "market": {
                        "observations": [
                            {"selection_team_id": str(team_a.id), "price": 2.0},
                            {"selection_team_id": str(team_b.id), "price": 2.0},
                        ]
                    },
                },
                snapshot_hash=f"benchmark-{index}-{uuid4()}",
            )
            session.add(snapshot)
            await session.flush()

            result = MapResultRecord(
                canonical_map_id=canonical_map.id,
                winner_team_id=team_a.id if team_a_won else team_b.id,
                basic_first_usable_at=NOW + timedelta(hours=index),
                provider_conflict=False,
            )
            session.add(result)

            baseline = _decision(
                snapshot,
                BASELINE,
                probability=baseline_probabilities[index - 1],
                action="BUY_A" if index == 1 else "NO_BUY",
                latency=float(index * 2 - 1),
            )
            challenger = _decision(
                snapshot,
                CHALLENGER,
                probability=challenger_probabilities[index - 1],
                action="BUY_A" if index == 1 else "BUY_B",
                latency=1.0,
            )
            session.add_all([baseline, challenger])
            await session.flush()
            session.add_all(
                [
                    _evaluation(
                        baseline.id,
                        baseline_probabilities[index - 1],
                        team_a_won,
                        clv=0.01,
                    ),
                    _evaluation(
                        challenger.id,
                        challenger_probabilities[index - 1],
                        team_a_won,
                        clv=0.03,
                    ),
                ]
            )

            # A later checkpoint on map 1 must affect attempts/actions but not forecast N.
            if index == 1:
                later_snapshot = DecisionSnapshotRecord(
                    id=uuid4(),
                    canonical_map_id=canonical_map.id,
                    decision_at=snapshot.decision_at + timedelta(minutes=5),
                    created_at=snapshot.created_at + timedelta(minutes=5),
                    mode="LIVE_BASIC",
                    canonical_payload=snapshot.canonical_payload,
                    snapshot_hash=f"benchmark-later-{uuid4()}",
                )
                session.add(later_snapshot)
                await session.flush()
                later = _decision(
                    later_snapshot,
                    BASELINE,
                    probability=0.99,
                    action="NO_BUY",
                    latency=9.0,
                )
                session.add(later)
                await session.flush()
                session.add(_evaluation(later.id, 0.99, team_a_won, clv=0.5))

        report = await AiBaselineBenchmarkService().build_report(session)

    contract = report["baseline_contract"]
    assert contract["id"] == BASELINE_ID
    assert contract["frozen_at_commit"] == BASELINE_FROZEN_AT_COMMIT
    assert contract["immutable"] is True
    assert report["methodology"]["calibration"]["version"] == "ece-equal-width-10-v1"

    rows = {row["experiment"]["prompt_version"]: row for row in report["experiments"]}
    baseline = rows[BASELINE_PROMPT_VERSION]
    challenger = rows[CHALLENGER[2]]

    assert baseline["baseline_role"] == "BASELINE"
    assert baseline["samples"]["attempts"] == 3
    assert baseline["samples"]["forecast_maps"] == 2
    assert baseline["samples"]["clv_maps"] == 2
    assert baseline["quality"]["forecast_accuracy"] == pytest.approx(0.5)
    assert baseline["quality"]["average_brier_score"] == pytest.approx(0.265)
    assert baseline["quality"]["calibration_error"] == pytest.approx(0.45)
    assert baseline["quality"]["abstention_rate"] == pytest.approx(2 / 3)
    assert baseline["quality"]["average_clv"] == pytest.approx(0.01)
    assert baseline["latency"]["average_seconds"] == pytest.approx(13 / 3)

    assert challenger["baseline_role"] == "CHALLENGER"
    assert challenger["baseline_reference"]["prompt_version"] == BASELINE_PROMPT_VERSION
    assert challenger["samples"]["forecast_maps"] == 2
    assert challenger["quality"]["forecast_accuracy"] == pytest.approx(1.0)
    assert challenger["quality"]["average_brier_score"] == pytest.approx(0.085)
    assert challenger["quality"]["calibration_error"] == pytest.approx(0.25)
    assert challenger["quality"]["abstention_rate"] == pytest.approx(0.0)
    assert challenger["quality"]["average_clv"] == pytest.approx(0.03)
    assert challenger["delta_vs_baseline"]["brier_improvement"] == pytest.approx(0.18)
    assert challenger["delta_vs_baseline"]["forecast_accuracy"] == pytest.approx(0.5)
    assert challenger["delta_vs_baseline"]["calibration_improvement"] == pytest.approx(0.2)

    await engine.dispose()


def _decision(
    snapshot: DecisionSnapshotRecord,
    identity: tuple[str, str, str, str, str],
    *,
    probability: float,
    action: str,
    latency: float,
) -> AiDecisionRecord:
    provider, model, prompt, policy, view = identity
    return AiDecisionRecord(
        snapshot_id=snapshot.id,
        snapshot_hash=snapshot.snapshot_hash,
        provider=provider,
        model=model,
        model_version=model,
        prompt_version=prompt,
        decision_policy_version=policy,
        ai_view_version=view,
        request_started_at=snapshot.decision_at,
        response_received_at=snapshot.decision_at + timedelta(seconds=latency),
        latency_seconds=latency,
        normalized_response={
            "action": action,
            "fair_probability_a": probability,
            "confidence": 0.8,
            "market_assessment": "UNDERPRICED",
            "minimum_acceptable_odds_a": 1.8 if action == "BUY_A" else None,
            "stake": 100.0 if action in {"BUY_A", "BUY_B"} else None,
            "primary_reasons": ["benchmark fixture"],
            "blockers": [],
        },
        raw_response={"fixture": True},
        parse_status="SUCCESS",
    )


def _evaluation(
    decision_id,
    probability: float,
    team_a_won: bool,
    *,
    clv: float,
) -> DecisionEvaluationRecord:
    probability = min(max(probability, 1e-12), 1.0 - 1e-12)
    brier = (probability - float(team_a_won)) ** 2
    loss = -(log(probability) if team_a_won else log(1.0 - probability))
    return DecisionEvaluationRecord(
        ai_decision_id=decision_id,
        result_correct=None,
        brier_score=brier,
        log_loss=loss,
        clv=clv,
        metrics_version="benchmark-test-v1",
    )
