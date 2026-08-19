from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import Base
from app.evaluation.readiness import DecisionReadinessService
from app.models import (
    AiDecisionRecord,
    CanonicalEvent,
    CanonicalMap,
    CanonicalSeries,
    CanonicalTeam,
    DecisionEvaluationRecord,
    DecisionSnapshotRecord,
    DltvLiveObservationRecord,
    DraftSnapshotRecord,
    MapResultRecord,
    OddsObservationRecord,
    ProviderMatchMapping,
)
from app.web.quality import create_quality_router


@pytest.mark.asyncio
async def test_readiness_funnel_is_cumulative_and_explains_first_blocker() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)

    async with factory.begin() as session:
        event = CanonicalEvent(name="The International 2026")
        liquid = CanonicalTeam(name="Team Liquid")
        spirit = CanonicalTeam(name="Team Spirit")
        falcons = CanonicalTeam(name="Team Falcons")
        tundra = CanonicalTeam(name="Tundra Esports")
        aurora = CanonicalTeam(name="Aurora")
        xg = CanonicalTeam(name="Xtreme Gaming")
        session.add_all((event, liquid, spirit, falcons, tundra, aurora, xg))
        await session.flush()

        evaluated = CanonicalSeries(
            event_id=event.id,
            team_a_id=liquid.id,
            team_b_id=spirit.id,
            best_of=3,
            scheduled_at=now - timedelta(hours=3),
        )
        draft_blocked = CanonicalSeries(
            event_id=event.id,
            team_a_id=falcons.id,
            team_b_id=tundra.id,
            best_of=3,
            scheduled_at=now - timedelta(hours=2),
        )
        no_raybet = CanonicalSeries(
            event_id=event.id,
            team_a_id=aurora.id,
            team_b_id=xg.id,
            best_of=3,
            scheduled_at=now - timedelta(hours=1),
        )
        session.add_all((evaluated, draft_blocked, no_raybet))
        await session.flush()

        for index, series in enumerate((evaluated, draft_blocked, no_raybet), start=1):
            session.add(
                ProviderMatchMapping(
                    provider="liquipedia",
                    provider_match_id=f"liq-{index}",
                    canonical_series_id=series.id,
                    resolved_by="LIQUIPEDIA_SCHEDULE",
                    confidence=0.99,
                )
            )
        for provider_match_id, series in ((101, evaluated), (202, draft_blocked)):
            session.add(
                ProviderMatchMapping(
                    provider="raybet",
                    provider_match_id=str(provider_match_id),
                    canonical_series_id=series.id,
                    resolved_by="LIQUIPEDIA_TEAMS_TIME_BO",
                    confidence=0.99,
                )
            )
            session.add(
                OddsObservationRecord(
                    provider_match_id=provider_match_id,
                    odds_id=provider_match_id * 10,
                    canonical_series_id=series.id,
                    market_type="Winner",
                    match_stage="r1",
                    selection_team_id=series.team_a_id,
                    price=Decimal("1.80"),
                    implied_probability=0.55,
                    normalized_status="OPEN_CONFIRMED",
                    metadata_version="test-v1",
                    received_at=now - timedelta(minutes=30),
                    raw_event_id=uuid4(),
                )
            )

        evaluated_map = CanonicalMap(
            series_id=evaluated.id,
            map_number=1,
            valve_match_id=9001,
        )
        blocked_map = CanonicalMap(
            series_id=draft_blocked.id,
            map_number=1,
            valve_match_id=9002,
        )
        session.add_all((evaluated_map, blocked_map))
        await session.flush()

        for canonical_map, valve_match_id in ((evaluated_map, 9001), (blocked_map, 9002)):
            session.add(
                DltvLiveObservationRecord(
                    canonical_map_id=canonical_map.id,
                    valve_match_id=valve_match_id,
                    game_time_seconds=900,
                    radiant_kills=8,
                    dire_kills=6,
                    radiant_nw_lead=1200,
                    received_at=now - timedelta(minutes=10),
                    payload_hash=f"live-{valve_match_id}",
                    last_message_received_at=now - timedelta(minutes=10),
                    last_state_change_received_at=now - timedelta(minutes=10),
                    raw_event_id=uuid4(),
                )
            )

        session.add(
            DraftSnapshotRecord(
                canonical_map_id=blocked_map.id,
                valve_match_id=9002,
                complete=False,
                blockers=["DRAFT_INCOMPLETE"],
                warnings=[],
                payload_hash="blocked-draft",
                statistics_cutoff=now - timedelta(minutes=20),
                observed_at=now - timedelta(minutes=20),
                raw_event_id=uuid4(),
            )
        )

        snapshot = DecisionSnapshotRecord(
            id=uuid4(),
            canonical_map_id=evaluated_map.id,
            decision_at=now - timedelta(minutes=5),
            created_at=now - timedelta(minutes=5),
            mode="LIVE_BASIC",
            canonical_payload={"quality": {"eligible": True}},
            snapshot_hash="readiness-evaluated-snapshot",
        )
        session.add(snapshot)
        await session.flush()
        decision = AiDecisionRecord(
            snapshot_id=snapshot.id,
            snapshot_hash=snapshot.snapshot_hash,
            provider="openai",
            model="gpt-5.6",
            model_version="gpt-5.6",
            prompt_version="decision-analyst-v5.1-output",
            decision_policy_version="shadow-tournament-portfolio-v3",
            ai_view_version="ai-view-v6",
            request_started_at=now - timedelta(minutes=4),
            response_received_at=now - timedelta(minutes=4, seconds=-1),
            parse_status="SUCCESS",
            normalized_response={"action": "NO_BUY"},
        )
        session.add(decision)
        session.add(
            MapResultRecord(
                canonical_map_id=evaluated_map.id,
                winner_team_id=liquid.id,
                basic_first_usable_at=now - timedelta(minutes=1),
                settled_at=now - timedelta(minutes=1),
            )
        )
        await session.flush()
        session.add(
            DecisionEvaluationRecord(
                ai_decision_id=decision.id,
                result_correct=True,
                brier_score=0.16,
                log_loss=0.42,
                metrics_version="decision-evaluation-v2",
            )
        )

    async with factory() as session:
        payload = await DecisionReadinessService().build_report(session, now=now)

    assert payload["scope"]["series_count"] == 3
    assert [(stage["key"], stage["count"]) for stage in payload["stages"]] == [
        ("scheduled", 3),
        ("market_linked", 2),
        ("market_ready", 2),
        ("map_identity", 2),
        ("live_ready", 2),
        ("snapshot_ready", 1),
        ("ai_decision", 1),
        ("result_ready", 1),
        ("evaluated", 1),
    ]
    by_teams = {
        f"{series['team_a']['name']} vs {series['team_b']['name']}": series
        for series in payload["series"]
    }
    assert by_teams["Team Liquid vs Team Spirit"]["current_stage"] == "EVALUATED"
    assert by_teams["Team Liquid vs Team Spirit"]["blocker"] is None
    assert by_teams["Team Falcons vs Tundra Esports"]["current_stage"] == "LIVE_READY"
    assert by_teams["Team Falcons vs Tundra Esports"]["blocker"] == {
        "stage": "snapshot_ready",
        "reason": "DRAFT_INCOMPLETE",
    }
    assert by_teams["Aurora vs Xtreme Gaming"]["blocker"] == {
        "stage": "market_linked",
        "reason": "MARKET_IDENTITY_MISSING",
    }
    reasons = {item["reason"]: item["count"] for item in payload["failure_reasons"]}
    assert reasons == {"DRAFT_INCOMPLETE": 1, "MARKET_IDENTITY_MISSING": 1}
    await engine.dispose()


@pytest.mark.asyncio
async def test_readiness_api_returns_stable_empty_report() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    app = FastAPI()
    app.include_router(create_quality_router(factory))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/review/ai-quality/readiness?lookback_hours=24")

    assert response.status_code == 200
    payload = response.json()
    assert payload["report_version"] == "decision-readiness-v1"
    assert payload["scope"]["series_count"] == 0
    assert len(payload["stages"]) == 9
    assert payload["failure_reasons"] == []
    assert payload["series"] == []
    await engine.dispose()
