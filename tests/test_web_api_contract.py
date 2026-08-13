from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.testclient import TestClient

from app.db import Base
from app.models import (
    CanonicalHero,
    CanonicalMap,
    CanonicalPlayer,
    CanonicalSeries,
    CanonicalTeam,
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
from app.web.api import _match_phase, create_app


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
async def test_match_feed_orders_earliest_scheduled_match_first() -> None:
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

    assert [item["team_a"]["name"] for item in payload] == ["Level Up", "Spirit"]
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


def test_status_websocket_serializes_runtime_timestamps(tmp_path: Path) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    health = HealthRegistry()
    app = create_app(factory, health, frontend_dist=tmp_path / "missing")

    with TestClient(app) as client:
        with client.websocket_connect("/ws/status") as websocket:
            payload = websocket.receive_json()

    assert isinstance(payload["observed_at"], str)
