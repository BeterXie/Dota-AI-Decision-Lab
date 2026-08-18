from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import Base
from app.identity.roster_models import TeamProfile, TeamRosterMembership
from app.identity.team_registry_population import TeamRegistryPopulationService
from app.models import CanonicalTeam, ProviderTeamMapping
from app.providers.common import TimedPayload
from app.repositories.raw import RawEventRepository
from app.runtime.health import HealthRegistry
from app.web import create_app


class FakeTeamRegistryClient:
    normalizer_version = "test-opendota"

    def __init__(self) -> None:
        self.observed_at = datetime(2026, 8, 18, 3, 0, tzinfo=UTC)

    async def get_team_catalog(self, page: int = 0) -> TimedPayload:
        return TimedPayload(
            payload=[{"team_id": 7654321, "name": "Team Example", "tag": "EX"}],
            request_started_at=self.observed_at - timedelta(seconds=1),
            received_at=self.observed_at,
        )

    async def get_team_players(self, team_id: str | int) -> TimedPayload:
        assert int(team_id) == 7654321
        return TimedPayload(
            payload=[
                {"account_id": 101, "name": "Carry", "is_current_team_member": True},
                {"account_id": 102, "name": "Mid", "is_current_team_member": True},
            ],
            request_started_at=self.observed_at,
            received_at=self.observed_at + timedelta(seconds=1),
        )


class ConflictingTeamRegistryClient(FakeTeamRegistryClient):
    async def get_team_players(self, team_id: str | int) -> TimedPayload:
        raise AssertionError("conflicting identity must not fetch or attach roster data")


@pytest.mark.asyncio
async def test_population_fills_missing_profile_and_roster_without_guessing_assets() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory.begin() as session:
        team = CanonicalTeam(name="Team Example")
        session.add(team)
        await session.flush()
        session.add(
            ProviderTeamMapping(
                provider="opendota",
                provider_team_id="7654321",
                canonical_team_id=team.id,
                observed_name="Team Example",
            )
        )

    service = TeamRegistryPopulationService(RawEventRepository())
    async with factory.begin() as session:
        results = await service.populate(
            session,
            FakeTeamRegistryClient(),
            canonical_team_ids=[team.id],
        )

    assert len(results) == 1
    assert results[0].slug == "team-example"
    assert results[0].roster is not None
    assert results[0].roster.current_players == 2

    async with factory() as session:
        profile = await session.get(TeamProfile, team.id)
        memberships = list(
            (
                await session.scalars(
                    select(TeamRosterMembership).where(
                        TeamRosterMembership.team_id == team.id,
                        TeamRosterMembership.valid_to.is_(None),
                    )
                )
            ).all()
        )
    assert profile is not None
    assert profile.short_name == "EX"
    assert profile.valve_team_id == 7654321
    assert profile.logo_source == "valve-steam"
    assert profile.logo_url == (
        "https://steamcdn-a.akamaihd.net/apps/dota2/images/team_logos/7654321.png"
    )
    assert len(memberships) == 2

    await engine.dispose()


@pytest.mark.asyncio
async def test_population_preserves_manually_maintained_profile_fields() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory.begin() as session:
        team = CanonicalTeam(name="Team Example")
        session.add(team)
        await session.flush()
        session.add_all(
            (
                ProviderTeamMapping(
                    provider="opendota",
                    provider_team_id="7654321",
                    canonical_team_id=team.id,
                    observed_name="Team Example",
                ),
                TeamProfile(
                    canonical_team_id=team.id,
                    slug="official-team-example",
                    short_name="MANUAL",
                    logo_url="https://cdn.cloudflare.steamstatic.com/apps/dota2/images/team_logos/7654321.png",
                    logo_source="official-manual",
                    source_url="https://www.dota2.com/esports",
                    observed_at=datetime(2026, 8, 17, 3, 0, tzinfo=UTC),
                ),
            )
        )

    async with factory.begin() as session:
        await TeamRegistryPopulationService(RawEventRepository()).populate(
            session,
            FakeTeamRegistryClient(),
            canonical_team_ids=[team.id],
        )

    async with factory() as session:
        profile = await session.get(TeamProfile, team.id)
    assert profile is not None
    assert profile.slug == "official-team-example"
    assert profile.short_name == "MANUAL"
    assert profile.logo_source == "official-manual"
    assert profile.source_url == "https://www.dota2.com/esports"
    assert profile.valve_team_id == 7654321

    await engine.dispose()


@pytest.mark.asyncio
async def test_population_skips_conflicting_maintained_valve_identity() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory.begin() as session:
        team = CanonicalTeam(name="Team Example")
        session.add(team)
        await session.flush()
        session.add_all(
            (
                ProviderTeamMapping(
                    provider="opendota",
                    provider_team_id="7654321",
                    canonical_team_id=team.id,
                    observed_name="Team Example",
                ),
                TeamProfile(
                    canonical_team_id=team.id,
                    slug="team-example",
                    valve_team_id=1111111,
                    source_url="https://www.dota2.com/esports",
                    observed_at=datetime(2026, 8, 17, 3, 0, tzinfo=UTC),
                ),
            )
        )

    async with factory.begin() as session:
        results = await TeamRegistryPopulationService(RawEventRepository()).populate(
            session,
            ConflictingTeamRegistryClient(),
            canonical_team_ids=[team.id],
        )

    assert results[0].skipped is True
    assert results[0].valve_team_id == 1111111
    assert results[0].roster is None

    async with factory() as session:
        membership_count = len(
            list(
                (
                    await session.scalars(
                        select(TeamRosterMembership).where(TeamRosterMembership.team_id == team.id)
                    )
                ).all()
            )
        )
    assert membership_count == 0

    await engine.dispose()


@pytest.mark.asyncio
async def test_team_detail_is_publicly_addressable_by_slug(tmp_path: Path) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory.begin() as session:
        team = CanonicalTeam(name="Team Example")
        session.add(team)
        await session.flush()
        session.add(
            TeamProfile(
                canonical_team_id=team.id,
                slug="team-example",
                valve_team_id=7654321,
                observed_at=datetime(2026, 8, 18, 3, 0, tzinfo=UTC),
            )
        )

    health = HealthRegistry()
    await health.dependency("DATABASE", "READY")
    app = create_app(factory, health, frontend_dist=tmp_path / "missing", auth_enabled=False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/teams/by-slug/team-example")

    assert response.status_code == 200
    assert response.json()["id"] == str(team.id)
    assert response.json()["slug"] == "team-example"

    await engine.dispose()
