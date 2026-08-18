from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import Base
from app.domain.identity import ProviderMatch
from app.identity.raybet_linking import RayBetExistingSeriesLinker
from app.identity.resolver import IdentityAmbiguousError, IdentityResolver
from app.models import (
    CanonicalEvent,
    CanonicalMap,
    CanonicalSeries,
    CanonicalTeam,
    ProviderEventMapping,
    ProviderMatchMapping,
    TeamAlias,
)
from app.providers.liquipedia.models import LiquipediaSeriesObservation
from app.providers.liquipedia.projection import LiquipediaCanonicalProjector


def _raybet_match(
    *,
    scheduled_at: datetime | None,
    tournament_name: str = "The International 2026",
    tournament_id: int = 77,
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
        tournament_id=tournament_id,
        tournament_name=tournament_name,
        team_a_id=101,
        team_a_name="Liquid",
        team_b_id=202,
        team_b_name="Spirit",
        round=round_name,
        provider_status=0,
        scheduled_at=scheduled_at,
        observed_at=observed_at,
    )


async def _project_liquipedia_series(
    session,
    *,
    scheduled_at: datetime,
    tournament_name: str = "The International 2026",
    tournament_page: str = "The International/2026",
    provider_key: str = "ti2026-liquid-spirit",
    best_of: int = 3,
) -> CanonicalSeries:
    projector = LiquipediaCanonicalProjector()
    await projector.project_series(
        session,
        [
            LiquipediaSeriesObservation(
                team_a_name="Team Liquid",
                team_a_page="Team Liquid",
                team_b_name="Team Spirit",
                team_b_page="Team Spirit",
                tournament_name=tournament_name,
                tournament_page=tournament_page,
                stage="Group Stage",
                best_of=best_of,
                scheduled_at=scheduled_at,
                state="UPCOMING",
                provider_key=provider_key,
            )
        ],
    )
    mapping = await session.scalar(
        select(ProviderMatchMapping).where(
            ProviderMatchMapping.provider == "liquipedia",
            ProviderMatchMapping.provider_match_id == provider_key,
        )
    )
    assert mapping is not None and mapping.canonical_series_id is not None
    series = await session.get(CanonicalSeries, mapping.canonical_series_id)
    assert series is not None
    return series


@pytest.mark.asyncio
async def test_raybet_links_to_event_compatible_liquipedia_series() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    scheduled_at = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)

    async with factory.begin() as session:
        series = await _project_liquipedia_series(session, scheduled_at=scheduled_at)
        series_id = series.id
        event_id = series.event_id

    match = _raybet_match(scheduled_at=scheduled_at + timedelta(minutes=12))
    async with factory.begin() as session:
        result = await RayBetExistingSeriesLinker().link(session, match)
        fallback_id = await IdentityResolver().observe_raybet_match(session, match)

    assert result.canonical_series_id == series_id
    assert result.fallback_allowed is False
    assert fallback_id == series_id
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(CanonicalSeries)) == 1
        raybet_mapping = await session.scalar(
            select(ProviderMatchMapping).where(ProviderMatchMapping.provider == "raybet")
        )
        assert raybet_mapping is not None
        assert raybet_mapping.canonical_series_id == series_id
        assert raybet_mapping.resolved_by == "LIQUIPEDIA_TEAMS_TIME_BO"
        event_mapping = await session.scalar(
            select(ProviderEventMapping).where(ProviderEventMapping.provider == "raybet")
        )
        assert event_mapping is not None
        assert event_mapping.canonical_event_id == event_id
    await engine.dispose()


@pytest.mark.asyncio
async def test_raybet_blocks_cross_tournament_fallback_even_with_one_time_candidate() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    scheduled_at = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)

    async with factory.begin() as session:
        await _project_liquipedia_series(
            session,
            scheduled_at=scheduled_at,
            tournament_name="DreamLeague Season 27",
            tournament_page="DreamLeague/Season_27",
            provider_key="dl27-liquid-spirit",
        )

    match = _raybet_match(
        scheduled_at=scheduled_at + timedelta(minutes=5),
        tournament_name="The International 2026",
    )
    async with factory.begin() as session:
        result = await RayBetExistingSeriesLinker().link(session, match)

    assert result.canonical_series_id is None
    assert result.fallback_allowed is False
    assert result.reason == "event_name_conflict"
    async with factory() as session:
        raybet_mapping_count = await session.scalar(
            select(func.count())
            .select_from(ProviderMatchMapping)
            .where(ProviderMatchMapping.provider == "raybet")
        )
        assert raybet_mapping_count == 0
    await engine.dispose()


@pytest.mark.asyncio
async def test_raybet_blocks_known_best_of_conflict() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    scheduled_at = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)

    async with factory.begin() as session:
        await _project_liquipedia_series(
            session,
            scheduled_at=scheduled_at,
            best_of=5,
        )

    match = _raybet_match(scheduled_at=scheduled_at, round_name="BO3")
    async with factory.begin() as session:
        result = await RayBetExistingSeriesLinker().link(session, match)

    assert result.canonical_series_id is None
    assert result.fallback_allowed is False
    assert result.reason == "best_of_conflict"
    await engine.dispose()


@pytest.mark.asyncio
async def test_raybet_linker_fails_closed_when_two_liquipedia_series_are_plausible() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    scheduled_at = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)

    async with factory.begin() as session:
        first = await _project_liquipedia_series(
            session,
            scheduled_at=scheduled_at,
            tournament_name="The International 2026",
            tournament_page="The International/2026/A",
            provider_key="series-a",
        )
        liquid_id = first.team_a_id
        spirit_id = first.team_b_id
        event = CanonicalEvent(name="The International 2026")
        session.add(event)
        await session.flush()
        second = CanonicalSeries(
            event_id=event.id,
            team_a_id=liquid_id,
            team_b_id=spirit_id,
            best_of=3,
            scheduled_at=scheduled_at + timedelta(minutes=10),
        )
        session.add(second)
        await session.flush()
        session.add(
            ProviderMatchMapping(
                provider="liquipedia",
                provider_match_id="series-b",
                canonical_series_id=second.id,
                resolved_by="LIQUIPEDIA_SCHEDULE",
                confidence=0.95,
            )
        )

    match = _raybet_match(scheduled_at=scheduled_at + timedelta(minutes=5))
    async with factory.begin() as session:
        with pytest.raises(IdentityAmbiguousError, match="RAYBET_EXISTING_SERIES_AMBIGUOUS"):
            await RayBetExistingSeriesLinker().link(session, match)
    await engine.dispose()


@pytest.mark.asyncio
async def test_raybet_first_fallback_reconciles_to_later_liquipedia_schedule() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    scheduled_at = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)
    match = _raybet_match(
        scheduled_at=scheduled_at,
        tournament_name="The International 2026",
    )

    async with factory.begin() as session:
        fallback_id = await IdentityResolver().observe_raybet_match(session, match)
        original_event_mapping = await session.scalar(
            select(ProviderEventMapping).where(ProviderEventMapping.provider == "raybet")
        )
        assert original_event_mapping is not None
        original_event_id = original_event_mapping.canonical_event_id

    async with factory.begin() as session:
        liquipedia = await _project_liquipedia_series(
            session,
            scheduled_at=scheduled_at + timedelta(minutes=10),
        )
        liquipedia_id = liquipedia.id
        liquipedia_event_id = liquipedia.event_id
        assert liquipedia_id != fallback_id

    async with factory.begin() as session:
        result = await RayBetExistingSeriesLinker().link(session, match)

    assert result.canonical_series_id == liquipedia_id
    assert result.reason == "reconciled_liquipedia_series"
    async with factory() as session:
        mapping = await session.scalar(
            select(ProviderMatchMapping).where(ProviderMatchMapping.provider == "raybet")
        )
        assert mapping is not None
        assert mapping.canonical_series_id == liquipedia_id
        assert mapping.resolved_by == "LIQUIPEDIA_RECONCILED_TEAMS_TIME_BO"
        event_mapping = await session.scalar(
            select(ProviderEventMapping).where(ProviderEventMapping.provider == "raybet")
        )
        assert event_mapping is not None
        assert event_mapping.canonical_event_id == liquipedia_event_id
        assert event_mapping.canonical_event_id != original_event_id
        assert await session.get(CanonicalSeries, fallback_id) is not None
    await engine.dispose()


@pytest.mark.asyncio
async def test_raybet_first_fallback_with_maps_is_not_rebound() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    scheduled_at = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)
    match = _raybet_match(scheduled_at=scheduled_at)

    async with factory.begin() as session:
        fallback_id = await IdentityResolver().observe_raybet_match(session, match)
        session.add(CanonicalMap(series_id=fallback_id, map_number=1))

    async with factory.begin() as session:
        await _project_liquipedia_series(
            session,
            scheduled_at=scheduled_at + timedelta(minutes=10),
        )

    async with factory.begin() as session:
        result = await RayBetExistingSeriesLinker().link(session, match)

    assert result.canonical_series_id == fallback_id
    assert result.fallback_allowed is False
    assert result.reason == "fallback_has_downstream_maps"
    await engine.dispose()
