from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

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
from app.web.review import _odds_review, _rosh_review, _snapshot_market_pair


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
                    "quality": {"eligible": True, "blockers": [], "warnings": []},
                    "market_type": "Winner",
                    "match_stage": "r1",
                    "observations": [
                        {"selection_team_id": str(team_a.id), "price": "2.20"},
                        {"selection_team_id": str(team_b.id), "price": "1.70"},
                    ],
                },
                "quality": {"eligible": True, "blockers": [], "warnings": []},
                "live": {"game_time_seconds": 1800},
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
    assert payload["pagination"] == {
        "limit": 100,
        "offset": 0,
        "returned": 1,
        "has_more": False,
        "next_offset": None,
    }
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


def _review_snapshot_record(
    *,
    decision_at: datetime,
    team_a_id: UUID,
    team_b_id: UUID,
    game_time_seconds: int = 700,
    snapshot_eligible: bool = True,
    market_eligible: bool = True,
    curve_points: list[dict] | None = None,
    canonical_map_id: UUID | None = None,
) -> DecisionSnapshotRecord:
    return DecisionSnapshotRecord(
        id=uuid4(),
        canonical_map_id=canonical_map_id or uuid4(),
        decision_at=decision_at,
        created_at=decision_at,
        mode="LIVE_BASIC",
        snapshot_hash=f"review-{uuid4()}",
        canonical_payload={
            "decision_at": decision_at.isoformat(),
            "identity": {
                "team_a": {"id": str(team_a_id), "name": "A"},
                "team_b": {"id": str(team_b_id), "name": "B"},
                "side_identity": {
                    "status": "RESOLVED",
                    "radiant_team_id": str(team_a_id),
                    "dire_team_id": str(team_b_id),
                },
            },
            "quality": {"eligible": snapshot_eligible, "blockers": [], "warnings": []},
            "live": {"game_time_seconds": game_time_seconds},
            "market": {
                "quality": {"eligible": market_eligible, "blockers": [], "warnings": []},
                "observations": [
                    {"selection_team_id": str(team_a_id), "price": "2.20"},
                    {"selection_team_id": str(team_b_id), "price": "1.70"},
                ],
            },
            "draft": {
                "curve": {
                    "model_version": "rosh-test",
                    "data_version": "data-test",
                    "points": curve_points or [],
                }
            },
        },
    )


def test_review_odds_start_requires_snapshot_market_and_ai_time_eligibility() -> None:
    now = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)
    team_a_id, team_b_id = uuid4(), uuid4()
    assert (
        _snapshot_market_pair(
            _review_snapshot_record(
                decision_at=now,
                team_a_id=team_a_id,
                team_b_id=team_b_id,
                game_time_seconds=599,
            )
        )
        is None
    )
    assert (
        _snapshot_market_pair(
            _review_snapshot_record(
                decision_at=now,
                team_a_id=team_a_id,
                team_b_id=team_b_id,
                market_eligible=False,
            )
        )
        is None
    )
    assert (
        _snapshot_market_pair(
            _review_snapshot_record(
                decision_at=now,
                team_a_id=team_a_id,
                team_b_id=team_b_id,
                snapshot_eligible=False,
            )
        )
        is None
    )
    eligible = _snapshot_market_pair(
        _review_snapshot_record(
            decision_at=now,
            team_a_id=team_a_id,
            team_b_id=team_b_id,
            game_time_seconds=600,
        )
    )
    assert eligible is not None
    assert eligible["odds_a"] == 2.2


def test_rosh_review_keeps_earliest_frozen_curve_when_later_snapshot_changes() -> None:
    now = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)
    team_a_id, team_b_id = uuid4(), uuid4()
    canonical_map_id = uuid4()
    early = _review_snapshot_record(
        decision_at=now,
        team_a_id=team_a_id,
        team_b_id=team_b_id,
        canonical_map_id=canonical_map_id,
        curve_points=[
            {"minute": 20, "pure_radiant_edge": 2.0, "adjusted_radiant_edge": 1.0},
            {"minute": 30, "pure_radiant_edge": 4.0, "adjusted_radiant_edge": -2.0},
            {"minute": 40, "pure_radiant_edge": 1.0, "adjusted_radiant_edge": -3.0},
        ],
    )
    late = _review_snapshot_record(
        decision_at=now + timedelta(minutes=5),
        team_a_id=team_a_id,
        team_b_id=team_b_id,
        canonical_map_id=canonical_map_id,
        curve_points=[
            {"minute": 20, "pure_radiant_edge": -20.0, "adjusted_radiant_edge": 20.0},
            {"minute": 30, "pure_radiant_edge": -30.0, "adjusted_radiant_edge": 30.0},
            {"minute": 40, "pure_radiant_edge": -40.0, "adjusted_radiant_edge": 40.0},
        ],
    )
    review = _rosh_review([early, late], winner_team_id=team_a_id)
    assert review is not None
    assert review["snapshot_id"] == str(early.id)
    assert review["reference"]["pure"]["edge_pp"] == 4.0
    assert review["reference"]["adjusted"]["edge_pp"] == -2.0


def test_rosh_reference_requires_exact_30_minute_point() -> None:
    now = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)
    team_a_id, team_b_id = uuid4(), uuid4()
    snapshot = _review_snapshot_record(
        decision_at=now,
        team_a_id=team_a_id,
        team_b_id=team_b_id,
        curve_points=[
            {"minute": 29, "pure_radiant_edge": 4.0, "adjusted_radiant_edge": 2.0},
            {"minute": 31, "pure_radiant_edge": 5.0, "adjusted_radiant_edge": 3.0},
        ],
    )
    review = _rosh_review([snapshot], winner_team_id=team_a_id)
    assert review is not None
    assert review["reference"] is None
    assert (
        next(item for item in review["points"] if item["minute"] == 30)["pure"]["edge_pp"] is None
    )


def test_review_odds_ignores_capture_without_any_timestamp() -> None:
    now = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)
    team_a_id, team_b_id = uuid4(), uuid4()
    snapshot = _review_snapshot_record(
        decision_at=now,
        team_a_id=team_a_id,
        team_b_id=team_b_id,
    )
    invalid_closing = SimpleNamespace(
        odds_a=Decimal("1.80"),
        odds_b=Decimal("2.05"),
        status="CAPTURED",
        observed_at=None,
        triggered_at=None,
    )
    review = _odds_review([snapshot], closings=[invalid_closing])
    assert review is not None
    assert review["end_kind"] == "LATEST_DECISION"


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
    assert payload["pagination"]["returned"] == 0
    await engine.dispose()
