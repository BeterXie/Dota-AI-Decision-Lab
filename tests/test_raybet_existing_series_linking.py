from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import Base
from app.domain.identity import ProviderMatch
from app.identity.aliases import normalize_alias
from app.identity.raybet_linking import RayBetExistingSeriesLinker
from app.identity.resolver import IdentityAmbiguousError, IdentityResolver
from app.models import (
    CanonicalEvent,
    CanonicalSeries,
    CanonicalTeam,
    ProviderEventMapping,
    ProviderMatchMapping,
    ProviderTeamMapping,
    TeamAlias,
)


def _raybet_match(
    *,
    scheduled_at: datetime | None,
    tournament_name: str = "The International 2026",
    round_name: str | None = "BO3",
) -> ProviderMatch:
    observed_at = (
        scheduled_at - timedelta(hours=2)
        if scheduled_at is not None
        else datetime(2026, 8, 18, 10, 0, tzinfo=UTC)
    )
    return ProviderMatch(
        provider_match_id=9001,
        game_id=151,
        tournament_id=77,
        tournament_name=tournament_name,
        team_a_id=101,
        team_a_name="Team Liquid",
        team_b_id=202,
        team_b_name="Team Spirit",
        round=round_name,
        provider_status=0,
        scheduled_at=scheduled_at,
        observed_at=observed_at,
    )


@pytest.mark.asyncio
async def test_raybet_links_to_existing_schedule_before_identity_fallback_creates_series() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    liquipedia_time = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)

    async with factory.begin() as session:
        event = CanonicalEvent(name="The International 2026")
        liquid = CanonicalTeam(name="Team Liquid")
        spirit = CanonicalTeam(name="Team Spirit")
        session.add_all((event, liquid, spirit))
        await session.flush()
        session.add_all(
            (
                TeamAlias(
                    canonical_team_id=liquid.id,
                    name="Team Liquid",
                    normalized_name=normalize_alias("Team Liquid"),
                    provider="liquipedia",
                ),
                TeamAlias(
                    canonical_team_id=spirit.id,
                    name="Team Spirit",
                    normalized_name=normalize_alias("Team Spirit"),
                    provider="liquipedia",
                ),
                ProviderTeamMapping(
                    provider="liquipedia",
                    provider_team_id="Team Liquid",
                    canonical_team_id=liquid.id,
                    observed_name="Team Liquid",
                ),
                ProviderTeamMapping(
                    provider="liquipedia",
                    provider_team_id="Team Spirit",
                    canonical_team_id=spirit.id,
                    observed_name="Team Spirit",
                ),
                ProviderEventMapping(
                    provider="liquipedia",
                    provider_event_id="The International/2026",
                    canonical_event_id=event.id,
                ),
            )
        )
        series = CanonicalSeries(
            event_id=event.id,
            team_a_id=liquid.id,
            team_b_id=spirit.id,
            scheduled_at=liquipedia_time,
        )
        session.add(series)
        await session.flush()
        series_id = series.id
        event_id = event.id

    match = _raybet_match(scheduled_at=liquipedia_time + timedelta(minutes=12))
    async with factory.begin() as session:
        linked_id = await RayBetExistingSeriesLinker().link(session, match)
        fallback_id = await IdentityResolver().observe_raybet_match(session, match)

    assert linked_id == series_id
    assert fallback_id == series_id
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(CanonicalSeries)) == 1
        mapping = await session.scalar(
            select(ProviderMatchMapping).where(ProviderMatchMapping.provider == "raybet")
        )
        assert mapping is not None
        assert mapping.canonical_series_id == series_id
        assert mapping.resolved_by == "EXISTING_CANONICAL_SERIES"
        raybet_event = await session.scalar(
            select(ProviderEventMapping).where(ProviderEventMapping.provider == "raybet")
        )
        assert raybet_event is not None
        assert raybet_event.canonical_event_id == event_id
        raybet_teams = list(
            (
                await session.scalars(
                    select(ProviderTeamMapping).where(ProviderTeamMapping.provider == "raybet")
                )
            ).all()
        )
        assert {item.provider_team_id for item in raybet_teams} == {"101", "202"}
        canonical = await session.get(CanonicalSeries, series_id)
        assert canonical is not None
        assert canonical.best_of == 3
        assert canonical.scheduled_at.replace(tzinfo=UTC) == liquipedia_time
    await engine.dispose()


@pytest.mark.asyncio
async def test_raybet_linker_fails_closed_when_two_existing_series_are_equally_plausible() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    scheduled_at = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)

    async with factory.begin() as session:
        liquid = CanonicalTeam(name="Team Liquid")
        spirit = CanonicalTeam(name="Team Spirit")
        event_a = CanonicalEvent(name="Event A")
        event_b = CanonicalEvent(name="Event B")
        session.add_all((liquid, spirit, event_a, event_b))
        await session.flush()
        session.add_all(
            (
                TeamAlias(
                    canonical_team_id=liquid.id,
                    name="Team Liquid",
                    normalized_name=normalize_alias("Team Liquid"),
                    provider="liquipedia",
                ),
                TeamAlias(
                    canonical_team_id=spirit.id,
                    name="Team Spirit",
                    normalized_name=normalize_alias("Team Spirit"),
                    provider="liquipedia",
                ),
                CanonicalSeries(
                    event_id=event_a.id,
                    team_a_id=liquid.id,
                    team_b_id=spirit.id,
                    scheduled_at=scheduled_at,
                ),
                CanonicalSeries(
                    event_id=event_b.id,
                    team_a_id=liquid.id,
                    team_b_id=spirit.id,
                    scheduled_at=scheduled_at + timedelta(minutes=5),
                ),
            )
        )

    match = _raybet_match(scheduled_at=scheduled_at, tournament_name="Unknown Event")
    async with factory.begin() as session:
        with pytest.raises(IdentityAmbiguousError, match="RAYBET_EXISTING_SERIES_AMBIGUOUS"):
            await RayBetExistingSeriesLinker().link(session, match)

    async with factory() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(ProviderMatchMapping)
                .where(ProviderMatchMapping.provider == "raybet")
            )
            == 0
        )
    await engine.dispose()


@pytest.mark.asyncio
async def test_raybet_linker_does_not_match_existing_series_without_schedule_time() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    scheduled_at = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)

    async with factory.begin() as session:
        liquid = CanonicalTeam(name="Team Liquid")
        spirit = CanonicalTeam(name="Team Spirit")
        session.add_all((liquid, spirit))
        await session.flush()
        session.add_all(
            (
                TeamAlias(
                    canonical_team_id=liquid.id,
                    name="Team Liquid",
                    normalized_name=normalize_alias("Team Liquid"),
                    provider="liquipedia",
                ),
                TeamAlias(
                    canonical_team_id=spirit.id,
                    name="Team Spirit",
                    normalized_name=normalize_alias("Team Spirit"),
                    provider="liquipedia",
                ),
            )
        )
        existing = CanonicalSeries(
            team_a_id=liquid.id,
            team_b_id=spirit.id,
            best_of=3,
            scheduled_at=scheduled_at,
        )
        session.add(existing)
        await session.flush()
        existing_id = existing.id

    match = _raybet_match(scheduled_at=None)
    async with factory.begin() as session:
        assert await RayBetExistingSeriesLinker().link(session, match) is None
        created_id = await IdentityResolver().observe_raybet_match(session, match)

    assert created_id != existing_id
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(CanonicalSeries)) == 2
        mapping = await session.scalar(
            select(ProviderMatchMapping).where(ProviderMatchMapping.provider == "raybet")
        )
        assert mapping is not None
        assert mapping.canonical_series_id == created_id
        assert mapping.resolved_by == "PROVIDER_DISCOVERY"
    await engine.dispose()


@pytest.mark.asyncio
async def test_raybet_linker_rejects_known_best_of_conflict() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    scheduled_at = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)

    async with factory.begin() as session:
        liquid = CanonicalTeam(name="Team Liquid")
        spirit = CanonicalTeam(name="Team Spirit")
        session.add_all((liquid, spirit))
        await session.flush()
        session.add_all(
            (
                TeamAlias(
                    canonical_team_id=liquid.id,
                    name="Team Liquid",
                    normalized_name=normalize_alias("Team Liquid"),
                    provider="liquipedia",
                ),
                TeamAlias(
                    canonical_team_id=spirit.id,
                    name="Team Spirit",
                    normalized_name=normalize_alias("Team Spirit"),
                    provider="liquipedia",
                ),
                CanonicalSeries(
                    team_a_id=liquid.id,
                    team_b_id=spirit.id,
                    best_of=5,
                    scheduled_at=scheduled_at,
                ),
            )
        )

    match = _raybet_match(scheduled_at=scheduled_at, round_name="BO3")
    async with factory.begin() as session:
        assert await RayBetExistingSeriesLinker().link(session, match) is None

    async with factory() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(ProviderMatchMapping)
                .where(ProviderMatchMapping.provider == "raybet")
            )
            == 0
        )
    await engine.dispose()
