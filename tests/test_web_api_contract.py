from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import WebSocketDisconnect
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import Base
from app.market.fair_probability import remove_vig
from app.models import (
    AiDecisionRecord,
    CanonicalHero,
    CanonicalMap,
    CanonicalPlayer,
    CanonicalSeries,
    CanonicalTeam,
    DecisionEvaluationRecord,
    DecisionSnapshotRecord,
    DltvLiveObservationRecord,
    DraftSlotRecord,
    DraftSnapshotRecord,
    MapResultRecord,
    OddsObservationRecord,
    ProviderMatchMapping,
    RayBetMatch,
    TeamRatingSnapshotRecord,
)
from app.runtime.health import HealthRegistry
from app.web.api import _decision_payload, _match_phase, create_app


def test_match_phase_uses_result_and_fresh_live_facts() -> None:
    now = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)
    live = DltvLiveObservationRecord(
        canonical_map_id=uuid4(),
        valve_match_id=8941656460,
        received_at=now - timedelta(seconds=20),
        payload_hash="phase-live",
        last_message_received_at=now - timedelta(seconds=20),
        last_state_change_received_at=now - timedelta(seconds=20),
        raw_event_id=uuid4(),
    )
    result = MapResultRecord(
        canonical_map_id=uuid4(),
        basic_first_usable_at=now,
        settled_at=now,
    )

    assert (
        _match_phase(
            scheduled_at=now + timedelta(hours=1),
            live=None,
            result=None,
            observed_at=now,
            live_state_max_age_seconds=45,
        )
        == "PREMATCH"
    )
    assert (
        _match_phase(
            scheduled_at=now - timedelta(hours=1),
            live=live,
            result=None,
            observed_at=now,
            live_state_max_age_seconds=45,
        )
        == "LIVE"
    )
    live.last_message_received_at = now - timedelta(seconds=46)
    assert (
        _match_phase(
            scheduled_at=now - timedelta(hours=1),
            live=live,
            result=None,
            observed_at=now,
            live_state_max_age_seconds=45,
        )
        == "AWAITING_RESULT"
    )
    assert (
        _match_phase(
            scheduled_at=now - timedelta(hours=1),
            live=live,
            result=result,
            observed_at=now,
            live_state_max_age_seconds=45,
        )
        == "POSTMATCH"
    )


def test_decision_payload_exposes_virtual_pnl_settlement() -> None:
    now = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)
    snapshot_id = uuid4()
    record = AiDecisionRecord(
        id=uuid4(),
        snapshot_id=snapshot_id,
        snapshot_hash="fixture-snapshot-hash",
        provider="openai",
        model="fixture-model",
        model_version="fixture-model",
        prompt_version="decision-analyst-v4",
        decision_policy_version="shadow-decision-v2",
        ai_view_version="ai-view-v4",
        request_started_at=now,
        parse_status="SUCCESS",
        normalized_response={"action": "BUY_A", "stake": 100.0},
        bankroll_before=Decimal("1000.00"),
        stake=Decimal("100.00"),
    )
    evaluation = DecisionEvaluationRecord(
        ai_decision_id=record.id,
        result_correct=True,
        virtual_pnl=Decimal("85.00"),
        virtual_odds=Decimal("1.85000"),
        unit_pnl=Decimal("0.75"),
        metrics_version="decision-evaluation-v2",
    )

    payload = _decision_payload(record, evaluation)

    assert payload["stake"] == 100.0
    assert payload["bankroll_before"] == 1000.0
    assert payload["evaluation"]["virtual_pnl"] == 85.0
    assert payload["evaluation"]["virtual_odds"] == 1.85
    assert payload["evaluation"]["unit_pnl"] == 0.75
    assert payload["evaluation"]["result_correct"] is True


@pytest.mark.asyncio
async def test_operational_api_contract_without_business_data(tmp_path: Path) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    health = HealthRegistry()
    await health.dependency("DATABASE", "READY")
    for provider in ("GPT", "CLAUDE", "GEMINI"):
        await health.dependency(provider, "ACTION_REQUIRED")
    app = create_app(factory, health, frontend_dist=tmp_path / "missing")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        process = await client.get("/health")
        readiness = await client.get("/ready")
        matches = await client.get("/api/matches")
        jobs = await client.get("/api/jobs/summary")
        missing = await client.get("/api/maps/11111111-1111-1111-1111-111111111111")

    assert process.status_code == 200
    assert readiness.status_code == 503
    assert readiness.json()["overall"] == "ACTION_REQUIRED"
    assert matches.status_code == 200 and matches.json() == []
    assert jobs.status_code == 200
    assert jobs.json() == {
        "by_status": {},
        "by_type": [],
        "oldest_pending_at": None,
        "recent_failures": [],
    }
    assert missing.status_code == 404
    await engine.dispose()


@pytest.mark.asyncio
async def test_map_api_uses_map_winner_market_beyond_recent_observation_window() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    observed_at = datetime(2026, 8, 13, 5, 0, tzinfo=UTC)
    async with factory.begin() as session:
        team_a = CanonicalTeam(name="Team Falcons")
        team_b = CanonicalTeam(name="LGD Gaming")
        session.add_all((team_a, team_b))
        await session.flush()
        series = CanonicalSeries(team_a_id=team_a.id, team_b_id=team_b.id)
        session.add(series)
        await session.flush()
        canonical_map = CanonicalMap(series_id=series.id, map_number=2)
        session.add(canonical_map)
        await session.flush()
        for odds_id, team_id, price in (
            (10, team_a.id, "1.01"),
            (11, team_b.id, "13.34"),
        ):
            session.add(
                OddsObservationRecord(
                    provider_match_id=38423248,
                    odds_id=odds_id,
                    canonical_series_id=series.id,
                    canonical_map_id=canonical_map.id,
                    market_type="Winner",
                    match_stage="r2",
                    selection_team_id=team_id,
                    price=price,
                    implied_probability=0.5,
                    raw_status=1,
                    normalized_status="UNKNOWN",
                    metadata_version="recorded-v1",
                    received_at=observed_at,
                    raw_event_id=uuid4(),
                )
            )
        # More than the old 64-row query window. These other-map observations
        # must not hide the correct Map 2 winner pair.
        for index in range(70):
            session.add(
                OddsObservationRecord(
                    provider_match_id=38423248,
                    odds_id=1000 + index,
                    canonical_series_id=series.id,
                    canonical_map_id=canonical_map.id,
                    market_type="Kill Handicap",
                    match_stage="r3",
                    price="1.90",
                    implied_probability=0.5,
                    raw_status=1,
                    normalized_status="UNKNOWN",
                    metadata_version="recorded-v1",
                    received_at=observed_at + timedelta(seconds=index + 1),
                    raw_event_id=uuid4(),
                )
            )
    app = create_app(factory, HealthRegistry())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        payload = (await client.get(f"/api/maps/{canonical_map.id}")).json()

    assert [(item["match_stage"], item["price"]) for item in payload["market"]] == [
        ("r2", "1.01000"),
        ("r2", "13.34000"),
    ]
    await engine.dispose()


@pytest.mark.asyncio
async def test_map_detail_exposes_real_market_timeline_and_separated_market_quality() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime.now(UTC)
    async with factory.begin() as session:
        team_a = CanonicalTeam(name="Team Falcons")
        team_b = CanonicalTeam(name="LGD Gaming")
        session.add_all((team_a, team_b))
        await session.flush()
        series = CanonicalSeries(team_a_id=team_a.id, team_b_id=team_b.id)
        session.add(series)
        await session.flush()
        canonical_map = CanonicalMap(series_id=series.id, map_number=1)
        session.add(canonical_map)
        await session.flush()
        session.add(
            ProviderMatchMapping(
                provider="raybet",
                provider_match_id="38423248",
                canonical_series_id=series.id,
                resolved_by="PROVIDER_DISCOVERY",
                confidence=1.0,
            )
        )
        for odds_id, team_id, price, seconds_ago in (
            (10, team_a.id, "1.72", 2),
            (11, team_b.id, "2.18", 1),
        ):
            session.add(
                OddsObservationRecord(
                    provider_match_id=38423248,
                    odds_id=odds_id,
                    canonical_series_id=series.id,
                    canonical_map_id=canonical_map.id,
                    market_type="Winner",
                    match_stage="r1",
                    selection_team_id=team_id,
                    price=price,
                    implied_probability=0.5,
                    normalized_status="OPEN_CONFIRMED",
                    metadata_version="live-v1",
                    received_at=now - timedelta(seconds=seconds_ago),
                    raw_event_id=uuid4(),
                )
            )
        # An older observation for team A: the market timeline must be real
        # history, not only the latest row per selection.
        session.add(
            OddsObservationRecord(
                provider_match_id=38423248,
                odds_id=10,
                canonical_series_id=series.id,
                canonical_map_id=canonical_map.id,
                market_type="Winner",
                match_stage="r1",
                selection_team_id=team_a.id,
                price="1.65",
                implied_probability=0.5,
                normalized_status="OPEN_CONFIRMED",
                metadata_version="live-v1",
                received_at=now - timedelta(minutes=2),
                raw_event_id=uuid4(),
            )
        )
        snapshot_market_quality = {
            "eligible": True,
            "blockers": [],
            "warnings": [],
            "metadata_version": "frozen-v1",
            "paired_at": (now - timedelta(minutes=1)).isoformat(),
            "pair_skew_seconds": 0.5,
        }
        session.add(
            DecisionSnapshotRecord(
                id=uuid4(),
                canonical_map_id=canonical_map.id,
                decision_at=now - timedelta(minutes=1),
                created_at=now - timedelta(minutes=1),
                mode="LIVE_BASIC",
                canonical_payload={
                    "market": {"quality": snapshot_market_quality},
                    "history": {},
                    "quality": {},
                },
                snapshot_hash="fixture-market-separation",
            )
        )

    app = create_app(factory, HealthRegistry())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        payload = (await client.get(f"/api/maps/{canonical_map.id}")).json()

    # Real timeline: chronological history for the pair's odds ids.
    assert [(item["odds_id"], item["price"]) for item in payload["market_timeline"]] == [
        (10, "1.65000"),
        (10, "1.72000"),
        (11, "2.18000"),
    ]
    # Current quality is evaluated from live observations, not the snapshot.
    current = payload["market_quality"]
    assert current is not None
    assert current["eligible"] is True
    assert current["metadata_version"] == "live-v1"
    # The derived current market carries vig-removed fair probabilities.
    view = payload["current_market_view"]
    assert view is not None
    fair_a, fair_b, implied_total = remove_vig(1.72, 2.18)
    assert view["team_a"]["fair_probability"] == pytest.approx(fair_a)
    assert view["team_b"]["fair_probability"] == pytest.approx(fair_b)
    assert view["overround"] == pytest.approx(implied_total - 1.0)
    assert payload["snapshot_market_quality"] == snapshot_market_quality
    assert payload["latest_snapshot"]["market_quality"] == snapshot_market_quality
    await engine.dispose()


@pytest.mark.asyncio
async def test_match_feed_separates_current_and_snapshot_market_quality() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime.now(UTC)
    async with factory.begin() as session:
        team_a = CanonicalTeam(name="Spirit")
        team_b = CanonicalTeam(name="Xtreme Gaming")
        session.add_all((team_a, team_b))
        await session.flush()
        series = CanonicalSeries(team_a_id=team_a.id, team_b_id=team_b.id)
        session.add(series)
        await session.flush()
        canonical_map = CanonicalMap(series_id=series.id, map_number=1)
        session.add(canonical_map)
        await session.flush()
        session.add_all(
            (
                ProviderMatchMapping(
                    provider="raybet",
                    provider_match_id="38423260",
                    canonical_series_id=series.id,
                    resolved_by="PROVIDER_DISCOVERY",
                    confidence=1.0,
                ),
                RayBetMatch(
                    provider_match_id=38423260,
                    game_id=4,
                    team_a_provider_id=1,
                    team_a_name="Spirit",
                    team_b_provider_id=2,
                    team_b_name="Xtreme Gaming",
                    scheduled_at=now - timedelta(hours=1),
                    observed_at=now,
                    raw_event_id=uuid4(),
                ),
            )
        )
        for odds_id, team_id, price in ((10, team_a.id, "1.80"), (11, team_b.id, "2.05")):
            session.add(
                OddsObservationRecord(
                    provider_match_id=38423260,
                    odds_id=odds_id,
                    canonical_series_id=series.id,
                    canonical_map_id=canonical_map.id,
                    market_type="Winner",
                    match_stage="r1",
                    selection_team_id=team_id,
                    price=price,
                    implied_probability=0.5,
                    normalized_status="OPEN_CONFIRMED",
                    metadata_version="live-v1",
                    received_at=now - timedelta(seconds=1),
                    raw_event_id=uuid4(),
                )
            )
        snapshot_market_quality = {
            "eligible": True,
            "blockers": [],
            "warnings": [],
            "metadata_version": "frozen-v1",
            "paired_at": now.isoformat(),
            "pair_skew_seconds": 0.0,
        }
        session.add(
            DecisionSnapshotRecord(
                id=uuid4(),
                canonical_map_id=canonical_map.id,
                decision_at=now,
                created_at=now,
                mode="LIVE_BASIC",
                canonical_payload={
                    "market": {"quality": snapshot_market_quality},
                    "history": {},
                    "quality": {},
                },
                snapshot_hash="fixture-summary-separation",
            )
        )

    app = create_app(factory, HealthRegistry())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/matches")

    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["market_quality"]["metadata_version"] == "live-v1"
    assert payload[0]["current_market_view"]["quality"]["metadata_version"] == "live-v1"
    assert payload[0]["current_market_view"]["team_a"]["fair_probability"] is not None
    assert payload[0]["snapshot_market_quality"]["metadata_version"] == "frozen-v1"
    assert payload[0]["latest_snapshot"]["market_quality"]["metadata_version"] == "frozen-v1"
    await engine.dispose()


@pytest.mark.asyncio
async def test_match_feed_includes_raybet_series_pending_map_identity() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    observed_at = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)
    async with factory.begin() as session:
        team_a = CanonicalTeam(name="Spirit")
        team_b = CanonicalTeam(name="Xtreme Gaming")
        session.add_all((team_a, team_b))
        await session.flush()
        series = CanonicalSeries(
            team_a_id=team_a.id,
            team_b_id=team_b.id,
            best_of=3,
            scheduled_at=observed_at,
        )
        session.add(series)
        await session.flush()
        historical_cutoff = datetime.now(UTC) - timedelta(hours=1)
        session.add_all(
            (
                ProviderMatchMapping(
                    provider="raybet",
                    provider_match_id="38423260",
                    canonical_series_id=series.id,
                    resolved_by="PROVIDER_DISCOVERY",
                    confidence=1.0,
                ),
                RayBetMatch(
                    provider_match_id=38423260,
                    game_id=4,
                    tournament_id=100,
                    tournament_name="TI15 International",
                    team_a_provider_id=1,
                    team_a_name="Spirit",
                    team_b_provider_id=2,
                    team_b_name="Xtreme Gaming",
                    round="bo3",
                    raw_status=1,
                    scheduled_at=observed_at,
                    observed_at=observed_at,
                    raw_event_id=uuid4(),
                ),
            )
        )
        await session.flush()
        session.add_all(
            (
                TeamRatingSnapshotRecord(
                    canonical_team_id=team_a.id,
                    rating=1600,
                    rating_before=1580,
                    opponent_rating_before=1500,
                    expected_probability=0.6,
                    result=1.0,
                    source_map_id=uuid4(),
                    knowledge_cutoff=historical_cutoff,
                    calculated_at=historical_cutoff,
                    model_version="elo-v1",
                ),
                TeamRatingSnapshotRecord(
                    canonical_team_id=team_b.id,
                    rating=1500,
                    rating_before=1510,
                    opponent_rating_before=1580,
                    expected_probability=0.4,
                    result=0.0,
                    source_map_id=uuid4(),
                    knowledge_cutoff=historical_cutoff,
                    calculated_at=historical_cutoff,
                    model_version="elo-v1",
                ),
            )
        )
    app = create_app(factory, HealthRegistry())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/matches")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["entity_type"] == "SERIES"
    assert payload[0]["identity_status"] == "PENDING_MAP_IDENTITY"
    assert payload[0]["series_id"] == str(series.id)
    assert payload[0]["canonical_map_id"] is None
    assert payload[0]["valve_match_id"] is None
    assert payload[0]["provider_match_id"] == 38423260
    assert payload[0]["tournament_name"] == "TI15 International"
    assert payload[0]["team_a"] == {"id": str(team_a.id), "name": "Spirit"}
    assert payload[0]["team_b"] == {"id": str(team_b.id), "name": "Xtreme Gaming"}
    assert payload[0]["historical_prewarm"]["team_strength_ready_count"] == 2
    assert payload[0]["historical_prewarm"]["player_form_ready_count"] == 0
    await engine.dispose()


@pytest.mark.asyncio
async def test_pending_series_query_count_does_not_grow_with_card_count() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def add_pending_series(start: int, count: int) -> None:
        async with factory.begin() as session:
            for index in range(start, start + count):
                team_a = CanonicalTeam(name=f"Batch A {index}")
                team_b = CanonicalTeam(name=f"Batch B {index}")
                session.add_all((team_a, team_b))
                await session.flush()
                series = CanonicalSeries(team_a_id=team_a.id, team_b_id=team_b.id)
                session.add(series)
                await session.flush()
                session.add(
                    ProviderMatchMapping(
                        provider="raybet",
                        provider_match_id=str(40_000 + index),
                        canonical_series_id=series.id,
                        resolved_by="PROVIDER_DISCOVERY",
                        confidence=1.0,
                    )
                )

    await add_pending_series(0, 1)
    app = create_app(factory, HealthRegistry())
    selected: list[str] = []

    def count_selects(*args) -> None:
        statement = args[2]
        if statement.lstrip().upper().startswith("SELECT"):
            selected.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", count_selects)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            first = await client.get("/api/matches")
            one_card_queries = len(selected)
            selected.clear()
            await add_pending_series(1, 5)
            many = await client.get("/api/matches")
            six_card_queries = len(selected)
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", count_selects)

    assert first.status_code == 200
    assert many.status_code == 200
    assert len(first.json()) == 1
    assert len(many.json()) == 6
    assert six_card_queries == one_card_queries
    assert six_card_queries < 15
    await engine.dispose()


@pytest.mark.asyncio
async def test_match_feed_orders_newest_scheduled_match_first() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    observed_at = datetime(2026, 8, 12, 4, 0, tzinfo=UTC)
    async with factory.begin() as session:
        for index, (team_a_name, team_b_name, scheduled_at) in enumerate(
            (
                ("Spirit", "Xtreme Gaming", datetime(2026, 8, 13, 5, 0, tzinfo=UTC)),
                ("Level Up", "Rune Eaters", datetime(2026, 8, 12, 9, 0, tzinfo=UTC)),
            ),
            start=1,
        ):
            team_a = CanonicalTeam(name=team_a_name)
            team_b = CanonicalTeam(name=team_b_name)
            session.add_all((team_a, team_b))
            await session.flush()
            series = CanonicalSeries(
                team_a_id=team_a.id,
                team_b_id=team_b.id,
                scheduled_at=scheduled_at,
            )
            session.add(series)
            await session.flush()
            provider_match_id = 38400000 + index
            session.add_all(
                (
                    ProviderMatchMapping(
                        provider="raybet",
                        provider_match_id=str(provider_match_id),
                        canonical_series_id=series.id,
                        resolved_by="PROVIDER_DISCOVERY",
                        confidence=1.0,
                    ),
                    RayBetMatch(
                        provider_match_id=provider_match_id,
                        game_id=4,
                        team_a_provider_id=index * 10,
                        team_a_name=team_a_name,
                        team_b_provider_id=index * 10 + 1,
                        team_b_name=team_b_name,
                        scheduled_at=scheduled_at,
                        observed_at=observed_at,
                        raw_event_id=uuid4(),
                    ),
                )
            )
    app = create_app(factory, HealthRegistry())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        payload = (await client.get("/api/matches")).json()

    assert [item["team_a"]["name"] for item in payload] == ["Spirit", "Level Up"]
    await engine.dispose()


@pytest.mark.asyncio
async def test_map_api_exposes_partial_lineup_and_readiness_counts() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    observed_at = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)
    async with factory.begin() as session:
        team_a = CanonicalTeam(name="Level Up")
        team_b = CanonicalTeam(name="Rune Eaters")
        player = CanonicalPlayer(account_id=418942836, name=None)
        hero = CanonicalHero(hero_id=145, name=None)
        session.add_all((team_a, team_b, player, hero))
        await session.flush()
        series = CanonicalSeries(team_a_id=team_a.id, team_b_id=team_b.id)
        session.add(series)
        await session.flush()
        canonical_map = CanonicalMap(series_id=series.id, valve_match_id=8941656460)
        session.add(canonical_map)
        await session.flush()
        draft = DraftSnapshotRecord(
            canonical_map_id=canonical_map.id,
            valve_match_id=8941656460,
            complete=False,
            blockers=["DRAFT_PARTIAL"],
            warnings=[],
            payload_hash="partial-draft",
            statistics_cutoff=observed_at,
            observed_at=observed_at,
            raw_event_id=uuid4(),
        )
        session.add(draft)
        await session.flush()
        session.add_all(
            (
                DraftSlotRecord(
                    draft_snapshot_id=draft.id,
                    side="radiant",
                    position=1,
                    account_id=player.account_id,
                    canonical_player_id=player.id,
                    hero_id=hero.hero_id,
                    source="DLTV_SLOT",
                    confidence=1.0,
                ),
                DraftSlotRecord(
                    draft_snapshot_id=draft.id,
                    side="dire",
                    position=1,
                    account_id=93526520,
                    hero_id=None,
                    source="DLTV_SLOT",
                    confidence=1.0,
                ),
            )
        )
        session.add(
            DltvLiveObservationRecord(
                canonical_map_id=canonical_map.id,
                valve_match_id=8941656460,
                game_time_seconds=125,
                radiant_kills=3,
                dire_kills=1,
                radiant_nw_lead=850,
                first_blood="radiant",
                source_game_time=125,
                received_at=observed_at,
                payload_hash="live-state",
                connection_id="connection-1",
                reconnect_generation=2,
                last_message_received_at=observed_at,
                last_state_change_received_at=observed_at,
                raw_event_id=uuid4(),
            )
        )
    app = create_app(factory, HealthRegistry())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        payload = (await client.get(f"/api/maps/{canonical_map.id}")).json()

    assert payload["draft"]["roster_ready_count"] == 2
    assert payload["draft"]["hero_ready_count"] == 1
    assert payload["draft"]["slots"][0]["account_id"] == 93526520
    assert payload["draft"]["slots"][0]["hero_id"] is None
    assert payload["draft"]["slots"][1]["account_id"] == 418942836
    assert payload["draft"]["slots"][1]["hero_id"] == 145
    assert payload["live"]["first_blood"] == "radiant"
    assert payload["live_timeline"][0]["first_blood"] == "radiant"
    await engine.dispose()


@pytest.mark.asyncio
async def test_map_detail_batches_draft_slot_lookups() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    observed_at = datetime.now(UTC) - timedelta(minutes=2)

    async with factory.begin() as session:
        team_a = CanonicalTeam(name="Batch Team A")
        team_b = CanonicalTeam(name="Batch Team B")
        session.add_all((team_a, team_b))
        await session.flush()
        series = CanonicalSeries(team_a_id=team_a.id, team_b_id=team_b.id)
        session.add(series)
        await session.flush()
        canonical_map = CanonicalMap(series_id=series.id, valve_match_id=9_000_000_001)
        player = CanonicalPlayer(account_id=10_001, name="Player 1")
        hero = CanonicalHero(hero_id=1, name="Hero 1")
        session.add_all((canonical_map, player, hero))
        await session.flush()
        first_draft = DraftSnapshotRecord(
            canonical_map_id=canonical_map.id,
            valve_match_id=canonical_map.valve_match_id,
            complete=False,
            blockers=["DRAFT_PARTIAL"],
            warnings=[],
            payload_hash="one-slot-draft",
            statistics_cutoff=observed_at,
            observed_at=observed_at,
            raw_event_id=uuid4(),
        )
        session.add(first_draft)
        await session.flush()
        session.add(
            DraftSlotRecord(
                draft_snapshot_id=first_draft.id,
                side="radiant",
                position=1,
                account_id=player.account_id,
                canonical_player_id=player.id,
                hero_id=hero.hero_id,
                source="DLTV_SLOT",
                confidence=1.0,
            )
        )

    app = create_app(factory, HealthRegistry())
    selected: list[str] = []

    def count_selects(*args) -> None:
        statement = args[2]
        if statement.lstrip().upper().startswith("SELECT"):
            selected.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", count_selects)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            first = await client.get(f"/api/maps/{canonical_map.id}")
            one_slot_queries = len(selected)
            selected.clear()
            async with factory.begin() as session:
                players = [
                    CanonicalPlayer(account_id=10_100 + index, name=f"Player {index}")
                    for index in range(10)
                ]
                heroes = [
                    CanonicalHero(hero_id=100 + index, name=f"Hero {index}") for index in range(10)
                ]
                session.add_all([*players, *heroes])
                await session.flush()
                full_draft = DraftSnapshotRecord(
                    canonical_map_id=canonical_map.id,
                    valve_match_id=canonical_map.valve_match_id,
                    complete=True,
                    blockers=[],
                    warnings=[],
                    payload_hash="ten-slot-draft",
                    statistics_cutoff=observed_at + timedelta(minutes=1),
                    observed_at=observed_at + timedelta(minutes=1),
                    raw_event_id=uuid4(),
                )
                session.add(full_draft)
                await session.flush()
                session.add_all(
                    [
                        DraftSlotRecord(
                            draft_snapshot_id=full_draft.id,
                            side="radiant" if index < 5 else "dire",
                            position=index % 5 + 1,
                            account_id=players[index].account_id,
                            canonical_player_id=players[index].id,
                            hero_id=heroes[index].hero_id,
                            source="DLTV_SLOT",
                            confidence=1.0,
                        )
                        for index in range(10)
                    ]
                )
            selected.clear()
            full = await client.get(f"/api/maps/{canonical_map.id}")
            ten_slot_queries = len(selected)
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", count_selects)

    assert first.status_code == 200
    assert full.status_code == 200
    assert len(full.json()["draft"]["slots"]) == 10
    assert ten_slot_queries == one_slot_queries
    assert ten_slot_queries < 30
    await engine.dispose()


@pytest.mark.asyncio
async def test_match_feed_excludes_maps_created_only_from_historical_providers() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    observed_at = datetime(2026, 8, 12, 4, 0, tzinfo=UTC)
    async with factory.begin() as session:
        team_a = CanonicalTeam(name="Historical Team A")
        team_b = CanonicalTeam(name="Historical Team B")
        session.add_all((team_a, team_b))
        await session.flush()
        series = CanonicalSeries(
            team_a_id=team_a.id,
            team_b_id=team_b.id,
            scheduled_at=observed_at,
        )
        session.add(series)
        await session.flush()
        historical_map = CanonicalMap(
            series_id=series.id,
            map_number=1,
            scheduled_at=observed_at,
        )
        session.add(historical_map)
        await session.flush()
        session.add(
            ProviderMatchMapping(
                provider="stratz",
                provider_match_id="8936072794",
                canonical_series_id=series.id,
                canonical_map_id=historical_map.id,
                resolved_by="VALVE_MATCH_ID",
                confidence=1.0,
            )
        )
    app = create_app(factory, HealthRegistry())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/matches")

    assert response.status_code == 200
    assert response.json() == []
    await engine.dispose()


@pytest.mark.asyncio
async def test_status_websocket_serializes_runtime_timestamps(tmp_path: Path) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    health = HealthRegistry()
    app = create_app(factory, health, frontend_dist=tmp_path / "missing")
    route = next(item for item in app.routes if getattr(item, "path", None) == "/ws/status")

    class CaptureSocket:
        payload = None

        async def accept(self) -> None:
            return None

        async def send_json(self, payload) -> None:
            self.payload = payload
            raise WebSocketDisconnect()

    websocket = CaptureSocket()
    await route.endpoint(websocket)
    assert websocket.payload is not None
    assert isinstance(websocket.payload["observed_at"], str)
    await engine.dispose()


@pytest.mark.asyncio
async def test_map_detail_exposes_checkpoint_decisions_beyond_the_latest_snapshot() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime.now(UTC)
    async with factory.begin() as session:
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
        first = DecisionSnapshotRecord(
            id=uuid4(),
            canonical_map_id=canonical_map.id,
            decision_at=now - timedelta(minutes=10),
            created_at=now - timedelta(minutes=10),
            mode="LIVE_BASIC",
            canonical_payload={},
            snapshot_hash="fixture-checkpoint-1",
        )
        second = DecisionSnapshotRecord(
            id=uuid4(),
            canonical_map_id=canonical_map.id,
            decision_at=now - timedelta(minutes=5),
            created_at=now - timedelta(minutes=5),
            mode="LIVE_BASIC",
            canonical_payload={},
            snapshot_hash="fixture-checkpoint-2",
        )
        session.add_all((first, second))
        await session.flush()
        session.add_all(
            (
                AiDecisionRecord(
                    id=uuid4(),
                    snapshot_id=first.id,
                    snapshot_hash="fixture-checkpoint-1",
                    provider="openai",
                    model="m",
                    model_version="m",
                    prompt_version="p",
                    decision_policy_version="d",
                    ai_view_version="ai-view-v2",
                    request_started_at=now,
                    parse_status="SUCCESS",
                    normalized_response={"action": "NO_BUY"},
                ),
                AiDecisionRecord(
                    id=uuid4(),
                    snapshot_id=second.id,
                    snapshot_hash="fixture-checkpoint-2",
                    provider="kimi",
                    model="m",
                    model_version="m",
                    prompt_version="p",
                    decision_policy_version="d",
                    ai_view_version="ai-view-v2",
                    request_started_at=now,
                    parse_status="SUCCESS",
                    normalized_response={"action": "NO_BUY"},
                ),
            )
        )

    app = create_app(factory, HealthRegistry())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        payload = (await client.get(f"/api/maps/{canonical_map.id}")).json()

    # The legacy `decisions` key stays scoped to the LATEST snapshot (header
    # median semantics), while checkpoint_decisions carries the full history.
    assert len(payload["decisions"]) == 1
    assert payload["decisions"][0]["provider"] == "kimi"
    by_provider = {item["provider"]: item for item in payload["checkpoint_decisions"]}
    assert set(by_provider) == {"openai", "kimi"}
    assert all(item["snapshot_mode"] == "LIVE_BASIC" for item in by_provider.values())
    assert all(
        item["snapshot_id"] in {str(first.id), str(second.id)} for item in by_provider.values()
    )
    assert all(
        item["bankroll_before"] is None and item["stake"] is None for item in by_provider.values()
    )
    assert by_provider["kimi"]["snapshot_decision_at"].startswith(
        second.decision_at.isoformat()[:16]
    )
    assert by_provider["openai"]["snapshot_decision_at"].startswith(
        first.decision_at.isoformat()[:16]
    )
    await engine.dispose()


@pytest.mark.asyncio
async def test_deciding_map_prefers_live_final_winner_market_over_delisted_r3() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime.now(UTC)
    async with factory.begin() as session:
        team_a = CanonicalTeam(name="VG")
        team_b = CanonicalTeam(name="GamerLegion")
        session.add_all((team_a, team_b))
        await session.flush()
        series = CanonicalSeries(team_a_id=team_a.id, team_b_id=team_b.id, best_of=3)
        session.add(series)
        await session.flush()
        deciding_map = CanonicalMap(series_id=series.id, map_number=3)
        other_map = CanonicalMap(series_id=series.id, map_number=2)
        session.add_all((deciding_map, other_map))
        await session.flush()

        def add_odds(*, odds_id, team_id, price, stage, status, received_at, canonical_map):
            session.add(
                OddsObservationRecord(
                    provider_match_id=1,
                    odds_id=odds_id,
                    canonical_series_id=series.id,
                    canonical_map_id=canonical_map.id,
                    market_type="Winner",
                    match_stage=stage,
                    selection_team_id=team_id,
                    price=price,
                    implied_probability=0.5,
                    normalized_status=status,
                    metadata_version="v1",
                    received_at=received_at,
                    raw_event_id=uuid4(),
                )
            )

        # Delisted deciding-map market: closed and stale.
        add_odds(
            odds_id=100,
            team_id=team_a.id,
            price="1.50",
            stage="r3",
            status="SUSPENDED",
            received_at=now - timedelta(minutes=10),
            canonical_map=deciding_map,
        )
        add_odds(
            odds_id=101,
            team_id=team_b.id,
            price="2.56",
            stage="r3",
            status="SUSPENDED",
            received_at=now - timedelta(minutes=10),
            canonical_map=deciding_map,
        )
        # Live series winner market, which IS the map winner for the deciding map.
        add_odds(
            odds_id=200,
            team_id=team_a.id,
            price="1.80",
            stage="final",
            status="OPEN_CONFIRMED",
            received_at=now - timedelta(seconds=2),
            canonical_map=deciding_map,
        )
        add_odds(
            odds_id=201,
            team_id=team_b.id,
            price="1.94",
            stage="final",
            status="OPEN_CONFIRMED",
            received_at=now - timedelta(seconds=2),
            canonical_map=deciding_map,
        )
        # Non-deciding map keeps a healthy per-map market.
        add_odds(
            odds_id=300,
            team_id=team_a.id,
            price="1.35",
            stage="r2",
            status="OPEN_CONFIRMED",
            received_at=now - timedelta(seconds=2),
            canonical_map=other_map,
        )
        add_odds(
            odds_id=301,
            team_id=team_b.id,
            price="3.10",
            stage="r2",
            status="OPEN_CONFIRMED",
            received_at=now - timedelta(seconds=2),
            canonical_map=other_map,
        )

    app = create_app(factory, HealthRegistry())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        deciding = (await client.get(f"/api/maps/{deciding_map.id}")).json()
        other = (await client.get(f"/api/maps/{other_map.id}")).json()

    assert [item["odds_id"] for item in deciding["market"]] == [200, 201]
    assert {item["match_stage"] for item in deciding["market"]} == {"final"}
    assert deciding["market_quality"]["eligible"] is True
    view = deciding["current_market_view"]
    assert view["team_a"]["price"] == "1.80000"
    assert view["team_b"]["fair_probability"] is not None
    assert view["overround"] is not None
    # The non-deciding map never falls back to the series winner market.
    assert [item["odds_id"] for item in other["market"]] == [300, 301]
    assert {item["match_stage"] for item in other["market"]} == {"r2"}
    await engine.dispose()


@pytest.mark.asyncio
async def test_match_feed_orders_by_coalesced_schedule_newest_first() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime.now(UTC)

    counter = 0

    async def make_series(name: str, scheduled_at):
        nonlocal counter
        counter += 1
        async with factory.begin() as session:
            team_a = CanonicalTeam(name=f"{name}-A")
            team_b = CanonicalTeam(name=f"{name}-B")
            session.add_all((team_a, team_b))
            await session.flush()
            series = CanonicalSeries(
                team_a_id=team_a.id, team_b_id=team_b.id, scheduled_at=scheduled_at
            )
            session.add(series)
            await session.flush()
            # Maps resolved from DLTV identity carry no scheduled_at of their
            # own; ordering must fall back to the series schedule.
            canonical_map = CanonicalMap(series_id=series.id, map_number=1)
            session.add(canonical_map)
            await session.flush()
            session.add(
                ProviderMatchMapping(
                    provider="raybet",
                    provider_match_id=str(900000000 + counter),
                    canonical_series_id=series.id,
                    resolved_by="PROVIDER_DISCOVERY",
                    confidence=1.0,
                )
            )
            return series.id

    earlier_series = await make_series("Earlier", now - timedelta(hours=2))
    later_series = await make_series("Later", now - timedelta(hours=1))

    app = create_app(factory, HealthRegistry())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        payload = (await client.get("/api/matches")).json()

    series_ids = [item["series_id"] for item in payload]
    assert series_ids.index(str(later_series)) < series_ids.index(str(earlier_series))
    await engine.dispose()


def test_canonical_decision_rounds_keeps_latest_successful_attempt_per_snapshot_and_model() -> None:
    from app.web.api import _canonical_decision_rounds

    snapshot_id = uuid4()
    now = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)
    base = {
        "snapshot_id": snapshot_id,
        "snapshot_hash": "fixture-snapshot-hash",
        "provider": "openai",
        "model": "fixture-model",
        "model_version": "fixture-model",
        "prompt_version": "prompt-v1",
        "decision_policy_version": "policy-v1",
        "ai_view_version": "ai-view-v1",
        "parse_status": "SUCCESS",
        "normalized_response": {"action": "BUY_A"},
    }
    old_success = AiDecisionRecord(
        id=uuid4(), request_started_at=now - timedelta(minutes=2), **base
    )
    new_failure = AiDecisionRecord(
        id=uuid4(),
        request_started_at=now - timedelta(minutes=1),
        parse_status="TIMEOUT",
        normalized_response=None,
        **{
            key: value
            for key, value in base.items()
            if key not in {"parse_status", "normalized_response"}
        },
    )
    newest_success = AiDecisionRecord(id=uuid4(), request_started_at=now, **base)
    other_model = AiDecisionRecord(
        id=uuid4(),
        request_started_at=now,
        **{**base, "model": "other-model"},
    )

    canonical = _canonical_decision_rounds([old_success, new_failure, newest_success, other_model])

    assert {(item.id, item.model) for item in canonical} == {
        (newest_success.id, "fixture-model"),
        (other_model.id, "other-model"),
    }


@pytest.mark.asyncio
async def test_ready_stays_available_for_degraded_dependencies() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    health = HealthRegistry()
    await health.dependency("DATABASE", "READY")
    await health.dependency("GPT", "DEGRADED", message="temporary provider issue")
    app = create_app(factory, health)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/ready")
    assert response.status_code == 200
    assert response.json()["overall"] == "DEGRADED"
    await engine.dispose()
