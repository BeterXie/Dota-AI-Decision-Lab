from datetime import UTC, datetime
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import Base
from app.identity.roster_models import (
    CanonicalStaff,
    PlayerProfile,
    TeamProfile,
    TeamRosterMembership,
)
from app.models import CanonicalPlayer, CanonicalTeam, ProviderTeamMapping
from app.runtime.health import HealthRegistry
from app.web import create_app


@pytest.mark.asyncio
async def test_team_directory_exposes_profile_and_current_roster(tmp_path: Path) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    observed_at = datetime(2026, 8, 18, 1, 0, tzinfo=UTC)

    async with factory.begin() as session:
        team = CanonicalTeam(name="Team Example")
        player = CanonicalPlayer(account_id=12345, name="Carry")
        coach = CanonicalStaff(name="Coach Example")
        session.add_all((team, player, coach))
        await session.flush()
        session.add(
            TeamProfile(
                canonical_team_id=team.id,
                slug="team-example",
                short_name="EX",
                valve_team_id=999999,
                country_code="JP",
                logo_url="https://steamcdn-a.akamaihd.net/apps/dota2/images/team_logos/999999.png",
                logo_source="valve-steam",
                source_url="https://www.dota2.com",
                observed_at=observed_at,
            )
        )
        session.add(
            PlayerProfile(
                canonical_player_id=player.id,
                real_name="Example Carry",
                country_code="JP",
                observed_at=observed_at,
            )
        )
        session.add_all(
            (
                TeamRosterMembership(
                    team_id=team.id,
                    player_id=player.id,
                    role="PLAYER",
                    position=1,
                    source_name="official-team-site",
                    source_url="https://www.dota2.com",
                    observed_at=observed_at,
                ),
                TeamRosterMembership(
                    team_id=team.id,
                    staff_id=coach.id,
                    role="COACH",
                    source_name="official-team-site",
                    source_url="https://www.dota2.com",
                    observed_at=observed_at,
                ),
            )
        )

    health = HealthRegistry()
    await health.dependency("DATABASE", "READY")
    app = create_app(factory, health, frontend_dist=tmp_path / "missing", auth_enabled=False)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        directory = await client.get("/api/teams")
        detail = await client.get(f"/api/teams/{team.id}")

    assert directory.status_code == 200
    assert directory.json() == [
        {
            "id": str(team.id),
            "name": "Team Example",
            "slug": "team-example",
            "short_name": "EX",
            "valve_team_id": 999999,
            "identity_source": "registry",
            "country_code": "JP",
            "logo_url": "https://steamcdn-a.akamaihd.net/apps/dota2/images/team_logos/999999.png",
            "logo_source": "valve-steam",
            "website_url": None,
            "source_url": "https://www.dota2.com",
            "observed_at": "2026-08-18T01:00:00Z",
        }
    ]
    payload = detail.json()
    assert payload["name"] == "Team Example"
    assert [item["role"] for item in payload["current_roster"]] == ["PLAYER", "COACH"]
    assert payload["current_roster"][0]["subject"]["name"] == "Carry"
    assert payload["current_roster"][0]["subject"]["real_name"] == "Example Carry"
    assert payload["current_roster"][1]["subject"]["name"] == "Coach Example"
    assert len(payload["roster_history"]) == 2

    await engine.dispose()


@pytest.mark.asyncio
async def test_team_directory_reuses_existing_opendota_team_mapping(tmp_path: Path) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory.begin() as session:
        team = CanonicalTeam(name="Mapped Team")
        session.add(team)
        await session.flush()
        session.add(
            ProviderTeamMapping(
                provider="opendota",
                provider_team_id="1234567",
                canonical_team_id=team.id,
                observed_name="Mapped Team",
            )
        )

    health = HealthRegistry()
    await health.dependency("DATABASE", "READY")
    app = create_app(factory, health, frontend_dist=tmp_path / "missing", auth_enabled=False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/teams")

    assert response.status_code == 200
    payload = response.json()[0]
    assert payload["valve_team_id"] == 1234567
    assert payload["identity_source"] == "opendota"
    assert payload["logo_source"] == "valve-steam"
    assert payload["source_url"] == "https://www.opendota.com/teams/1234567"
    await engine.dispose()


@pytest.mark.asyncio
async def test_roster_history_keeps_closed_memberships(tmp_path: Path) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    joined_at = datetime(2025, 1, 1, tzinfo=UTC)
    left_at = datetime(2026, 1, 1, tzinfo=UTC)

    async with factory.begin() as session:
        team = CanonicalTeam(name="Historical Team")
        player = CanonicalPlayer(account_id=67890, name="Former Player")
        session.add_all((team, player))
        await session.flush()
        session.add(
            TeamRosterMembership(
                team_id=team.id,
                player_id=player.id,
                role="PLAYER",
                position=4,
                valid_from=joined_at,
                valid_to=left_at,
                source_name="official-announcement",
                observed_at=left_at,
            )
        )

    health = HealthRegistry()
    await health.dependency("DATABASE", "READY")
    app = create_app(factory, health, frontend_dist=tmp_path / "missing", auth_enabled=False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/teams/{team.id}")

    assert response.status_code == 200
    assert response.json()["current_roster"] == []
    assert response.json()["roster_history"][0]["valid_to"] == "2026-01-01T00:00:00Z"
    await engine.dispose()
