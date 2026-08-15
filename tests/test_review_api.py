from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import Base
from app.models import (
    AiDecisionRecord,
    CanonicalMap,
    CanonicalSeries,
    CanonicalTeam,
    DecisionEvaluationRecord,
    DecisionFutureOdds,
    DecisionSnapshotRecord,
    MapResultRecord,
)
from app.runtime.health import HealthRegistry
from app.web.api import create_app


@pytest.mark.asyncio
async def test_review_api_uses_frozen_rosh_canonical_ai_rounds_and_closing_odds() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)

    async with factory.begin() as session:
        team_a = CanonicalTeam(name="Team A")
        team_b = CanonicalTeam(name="Team B")
        session.add_all((team_a, team_b))
        await session.flush()
        series = CanonicalSeries(
            team_a_id=team_a.id,
            team_b_id=team_b.id,
            scheduled_at=now - timedelta(hours=2),
            best_of=3,
        )
        session.add(series)
        await session.flush()
        canonical_map = CanonicalMap(
            series_id=series.id,
            map_number=1,
            scheduled_at=now - timedelta(hours=2),
        )
        session.add(canonical_map)
        await session.flush()

        snapshot = DecisionSnapshotRecord(
            id=uuid4(),
            canonical_map_id=canonical_map.id,
            decision_at=now - timedelta(hours=1, minutes=30),
            created_at=now - timedelta(hours=1, minutes=30),
            mode="POST_DRAFT",
            snapshot_hash="review-snapshot-1",
            canonical_payload={
                "identity": {
                    "team_a": {"id": str(team_a.id), "name": team_a.name},
                    "team_b": {"id": str(team_b.id), "name": team_b.name},
                    "side_identity": {
                        "status": "RESOLVED",
                        "radiant_team_id": str(team_a.id),
                        "dire_team_id": str(team_b.id),
                    },
                },
                "market": {
                    "market_type": "Winner",
                    "match_stage": "r1",
                    "observations": [
                        {"selection_team_id": str(team_a.id), "price": "2.20"},
                        {"selection_team_id": str(team_b.id), "price": "1.70"},
                    ],
                },
                "draft": {
                    "curve": {
                        "model_version": "rosh-v-test",
                        "data_version": "data-v-test",
                        "points": [
                            {
                                "minute": 20,
                                "pure_radiant_edge": 2.0,
                                "adjusted_radiant_edge": 1.0,
                            },
                            {
                                "minute": 30,
                                "pure_radiant_edge": 4.0,
                                "adjusted_radiant_edge": -2.0,
                            },
                            {
                                "minute": 40,
                                "pure_radiant_edge": 1.5,
                                "adjusted_radiant_edge": -4.0,
                            },
                        ],
                    }
                },
            },
        )
        session.add(snapshot)
        await session.flush()

        older = AiDecisionRecord(
            id=uuid4(),
            snapshot_id=snapshot.id,
            snapshot_hash=snapshot.snapshot_hash,
            provider="openai",
            model="gpt-test",
            model_version="gpt-test",
            prompt_version="decision-analyst-v4",
            decision_policy_version="shadow-decision-v2",
            ai_view_version="ai-view-v5",
            request_started_at=now - timedelta(hours=1, minutes=29),
            parse_status="SUCCESS",
            normalized_response={
                "action": "BUY_B",
                "fair_probability_a": 0.45,
                "confidence": 0.6,
                "market_assessment": "FAIR",
                "minimum_acceptable_odds_a": None,
                "stake": 100.0,
                "primary_reasons": ["old"],
                "blockers": [],
            },
            stake=Decimal("100.00"),
        )
        newer = AiDecisionRecord(
            id=uuid4(),
            snapshot_id=snapshot.id,
            snapshot_hash=snapshot.snapshot_hash,
            provider="openai",
            model="gpt-test",
            model_version="gpt-test",
            prompt_version="decision-analyst-v5.1-output",
            decision_policy_version="shadow-decision-v2",
            ai_view_version="ai-view-v6",
            request_started_at=now - timedelta(hours=1, minutes=28),
            parse_status="SUCCESS",
            normalized_response={
                "action": "BUY_A",
                "fair_probability_a": 0.62,
                "confidence": 0.72,
                "market_assessment": "UNDERPRICED",
                "minimum_acceptable_odds_a": 1.9,
                "stake": 100.0,
                "primary_reasons": ["new"],
                "blockers": [],
            },
            stake=Decimal("100.00"),
        )
        session.add_all((older, newer))
        await session.flush()
        session.add_all(
            (
                DecisionEvaluationRecord(
                    ai_decision_id=older.id,
                    result_correct=False,
                    brier_score=0.30,
                    log_loss=0.80,
                    unit_pnl=Decimal("-1.00"),
                    metrics_version="decision-evaluation-v3",
                ),
                DecisionEvaluationRecord(
                    ai_decision_id=newer.id,
                    result_correct=True,
                    brier_score=0.14,
                    log_loss=0.48,
                    unit_pnl=Decimal("1.20"),
                    metrics_version="decision-evaluation-v3",
                ),
            )
        )
        session.add(
            DecisionFutureOdds(
                decision_snapshot_id=snapshot.id,
                capture_type="CLOSING",
                horizon_seconds=None,
                triggered_at=now - timedelta(minutes=5),
                due_at=now - timedelta(minutes=5),
                observed_at=now - timedelta(minutes=4),
                odds_a=Decimal("1.80"),
                odds_b=Decimal("2.05"),
                market_type="Winner",
                match_stage="r1",
                market_status="OPEN",
                capture_policy_version="closing-v1",
                pair_quality={},
                pair_skew_seconds=0.2,
                status="CAPTURED",
            )
        )
        session.add(
            MapResultRecord(
                canonical_map_id=canonical_map.id,
                winner_team_id=team_a.id,
                basic_first_usable_at=now,
                settled_at=now,
                provider_conflict=False,
            )
        )

    app = create_app(factory, HealthRegistry())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/review/matches")

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"]["settled_maps"] == 1
    assert payload["summary"]["rosh"]["pure"] == {
        "evaluated": 1,
        "correct": 1,
        "accuracy": 1.0,
    }
    assert payload["summary"]["rosh"]["adjusted"] == {
        "evaluated": 1,
        "correct": 0,
        "accuracy": 0.0,
    }
    assert payload["summary"]["odds"]["closing_coverage"] == 1.0

    ai = payload["summary"]["ai"]
    assert len(ai) == 1
    assert ai[0]["rounds"] == 1
    assert ai[0]["buy_decisions"] == 1
    assert ai[0]["correct_buy_decisions"] == 1
    assert ai[0]["buy_accuracy"] == 1.0
    assert ai[0]["average_brier"] == pytest.approx(0.14)
    assert ai[0]["unit_roi"] == pytest.approx(1.2)
    assert ai[0]["latest"]["action"] == "BUY_A"

    match = payload["matches"][0]
    assert match["winner_team_id"] == str(team_a.id)
    assert match["rosh"]["reference"]["pure"]["favored_team_id"] == str(team_a.id)
    assert match["rosh"]["reference"]["adjusted"]["favored_team_id"] == str(team_b.id)
    assert match["odds"]["start"]["odds_a"] == 2.2
    assert match["odds"]["end"]["odds_a"] == 1.8
    assert match["odds"]["end_kind"] == "CLOSING"
    assert match["odds"]["team_a_fair_probability_change_pp"] > 0

    await engine.dispose()


@pytest.mark.asyncio
async def test_review_api_empty_contract() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    app = create_app(factory, HealthRegistry())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/review/matches")

    assert response.status_code == 200
    payload = response.json()
    assert payload["matches"] == []
    assert payload["summary"]["settled_maps"] == 0
    assert payload["summary"]["rosh"]["adjusted"]["accuracy"] is None
    await engine.dispose()
