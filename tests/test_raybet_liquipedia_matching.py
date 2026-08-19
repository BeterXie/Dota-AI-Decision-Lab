from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import Base
from app.domain.identity import ProviderMatch
from app.identity.resolver import IdentityAmbiguousError, IdentityResolver
from app.models import (
    CanonicalEvent,
    CanonicalSeries,
    CanonicalTeam,
    ProviderEventMapping,
    ProviderMatchMapping,
    TeamAlias,
)
from app.providers.liquipedia.models import LiquipediaSeriesObservation
from app.providers.liquipedia.projection import LiquipediaCanonicalProjector


@pytest.mark.asyncio
async def test_raybet_without_liquipedia_identity_stays_unresolved() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    resolver = IdentityResolver()
    scheduled_at = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)

    with pytest.raises(IdentityAmbiguousError, match="RAYBET_LIQUIPEDIA_SERIES_REQUIRED"):
        async with factory.begin() as session:
            await resolver.observe_raybet_match(
                session,
                ProviderMatch(
                    provider_match_id=38423263,
                    game_id=151,
                    tournament_id=9001,
                    tournament_name="TI 2026",
                    team_a_id=16236,
                    team_a_name="Spirit",
                    team_b_id=16129,
                    team_b_name="Liquid",
                    round="bo3",
                    provider_status=1,
                    scheduled_at=scheduled_at,
                    observed_at=scheduled_at,
                ),
            )

    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(CanonicalEvent)) == 0
        assert await session.scalar(select(func.count()).select_from(CanonicalSeries)) == 0
        assert await session.scalar(select(func.count()).select_from(ProviderMatchMapping)) == 0
    await engine.dispose()


@pytest.mark.asyncio
async def test_raybet_reuses_liquipedia_series_and_event_identity() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    projector = LiquipediaCanonicalProjector()
    resolver = IdentityResolver()
    scheduled_at = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)
    observation = LiquipediaSeriesObservation(
        team_a_name="Team Liquid",
        team_a_page="Team Liquid",
        team_b_name="Team Spirit",
        team_b_page="Team Spirit",
        tournament_name="The International 2026",
        tournament_page="The International/2026",
        stage="Group Stage",
        best_of=3,
        scheduled_at=scheduled_at,
        state="UPCOMING",
        provider_key="ti2026-liquid-spirit",
    )

    async with factory.begin() as session:
        await projector.project_series(session, [observation])
        liquipedia_mapping = await session.scalar(
            select(ProviderMatchMapping).where(ProviderMatchMapping.provider == "liquipedia")
        )
        assert liquipedia_mapping is not None
        canonical_series_id = liquipedia_mapping.canonical_series_id
        assert canonical_series_id is not None
        canonical_series = await session.get(CanonicalSeries, canonical_series_id)
        assert canonical_series is not None
        canonical_event_id = canonical_series.event_id
        assert canonical_event_id is not None

    raybet_time = scheduled_at + timedelta(minutes=25)
    async with factory.begin() as session:
        resolved_id = await resolver.observe_raybet_match(
            session,
            ProviderMatch(
                provider_match_id=38423263,
                game_id=151,
                tournament_id=9001,
                tournament_name="TI 2026",
                team_a_id=16236,
                team_a_name="Spirit",
                team_b_id=16129,
                team_b_name="Liquid",
                round="bo3",
                provider_status=1,
                scheduled_at=raybet_time,
                observed_at=raybet_time,
            ),
        )

    assert resolved_id == canonical_series_id
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(CanonicalSeries)) == 1
        assert await session.scalar(select(func.count()).select_from(CanonicalEvent)) == 1
        raybet_mapping = await session.scalar(
            select(ProviderMatchMapping).where(ProviderMatchMapping.provider == "raybet")
        )
        assert raybet_mapping is not None
        assert raybet_mapping.canonical_series_id == canonical_series_id
        assert raybet_mapping.resolved_by == "LIQUIPEDIA_TEAMS_TIME_BO"
        assert raybet_mapping.confidence == pytest.approx(0.99)
        raybet_event = await session.scalar(
            select(ProviderEventMapping).where(ProviderEventMapping.provider == "raybet")
        )
        assert raybet_event is not None
        assert raybet_event.canonical_event_id == canonical_event_id
    await engine.dispose()


@pytest.mark.asyncio
async def test_raybet_refuses_ambiguous_liquipedia_series_candidates() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    resolver = IdentityResolver()
    scheduled_at = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)

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
                    normalized_name="team liquid",
                    provider="liquipedia",
                ),
                TeamAlias(
                    canonical_team_id=spirit.id,
                    name="Team Spirit",
                    normalized_name="team spirit",
                    provider="liquipedia",
                ),
            )
        )
        first = CanonicalSeries(
            event_id=event.id,
            team_a_id=liquid.id,
            team_b_id=spirit.id,
            best_of=3,
            scheduled_at=scheduled_at,
        )
        second = CanonicalSeries(
            event_id=event.id,
            team_a_id=liquid.id,
            team_b_id=spirit.id,
            best_of=3,
            scheduled_at=scheduled_at + timedelta(minutes=30),
        )
        session.add_all((first, second))
        await session.flush()
        session.add_all(
            (
                ProviderMatchMapping(
                    provider="liquipedia",
                    provider_match_id="series-a",
                    canonical_series_id=first.id,
                    resolved_by="LIQUIPEDIA_SCHEDULE",
                    confidence=0.95,
                ),
                ProviderMatchMapping(
                    provider="liquipedia",
                    provider_match_id="series-b",
                    canonical_series_id=second.id,
                    resolved_by="LIQUIPEDIA_SCHEDULE",
                    confidence=0.95,
                ),
            )
        )

    raybet_time = scheduled_at + timedelta(minutes=15)
    async with factory.begin() as session:
        with pytest.raises(
            IdentityAmbiguousError,
            match="RAYBET_LIQUIPEDIA_SERIES_AMBIGUOUS",
        ):
            await resolver.observe_raybet_match(
                session,
                ProviderMatch(
                    provider_match_id=38423264,
                    game_id=151,
                    tournament_id=9001,
                    tournament_name="TI 2026",
                    team_a_id=16129,
                    team_a_name="Liquid",
                    team_b_id=16236,
                    team_b_name="Spirit",
                    round="bo3",
                    provider_status=1,
                    scheduled_at=raybet_time,
                    observed_at=raybet_time,
                ),
            )
    await engine.dispose()
