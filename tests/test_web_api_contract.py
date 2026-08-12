from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.testclient import TestClient

from app.db import Base
from app.models import (
    CanonicalMap,
    CanonicalSeries,
    CanonicalTeam,
    ProviderMatchMapping,
    RayBetMatch,
    TeamRatingSnapshotRecord,
)
from app.runtime.health import HealthRegistry
from app.web.api import create_app


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
