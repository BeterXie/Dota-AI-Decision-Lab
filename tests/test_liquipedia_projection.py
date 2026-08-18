from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import Base
from app.models import (
    CanonicalEvent,
    CanonicalSeries,
    CanonicalTeam,
    ProviderEventMapping,
    ProviderMatchMapping,
    ProviderTeamMapping,
    TeamAlias,
)
from app.providers.liquipedia.models import (
    LiquipediaSeriesObservation,
    LiquipediaTournamentObservation,
)
from app.providers.liquipedia.projection import LiquipediaCanonicalProjector


@pytest.mark.asyncio
async def test_liquipedia_directory_and_schedule_seed_canonical_identity_idempotently() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    projector = LiquipediaCanonicalProjector()
    scheduled_at = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)
    tournament = LiquipediaTournamentObservation(
        page_name="The International/2026",
        name="The International 2026",
        phase="UPCOMING",
        tier="Tier 1",
        date_label="Aug 13 - 23, 2026",
        source_href="/dota2/The_International/2026",
    )
    series = LiquipediaSeriesObservation(
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
        event_result = await projector.project_tournaments(session, [tournament])
        first = await projector.project_series(session, [series])
    async with factory.begin() as session:
        second = await projector.project_series(session, [series])

    assert event_result.events_observed == 1
    assert first.series_created == 1
    assert second.series_reused == 1
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(CanonicalEvent)) == 1
        assert await session.scalar(select(func.count()).select_from(CanonicalSeries)) == 1
        canonical = await session.scalar(select(CanonicalSeries))
        assert canonical is not None
        assert canonical.stage_key == "GROUP_STAGE"
        assert await session.scalar(select(func.count()).select_from(CanonicalTeam)) == 2
        assert await session.scalar(select(func.count()).select_from(ProviderEventMapping)) == 1
        assert await session.scalar(select(func.count()).select_from(ProviderMatchMapping)) == 1
        assert await session.scalar(select(func.count()).select_from(ProviderTeamMapping)) == 2
    await engine.dispose()


@pytest.mark.asyncio
async def test_liquipedia_reuses_existing_raybet_team_aliases_and_nearby_series() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    projector = LiquipediaCanonicalProjector()
    scheduled_at = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)

    async with factory.begin() as session:
        event = CanonicalEvent(name="The International 2026")
        liquid = CanonicalTeam(name="Liquid")
        spirit = CanonicalTeam(name="Team Spirit")
        session.add_all((event, liquid, spirit))
        await session.flush()
        session.add_all(
            (
                TeamAlias(
                    canonical_team_id=liquid.id,
                    name="Team Liquid",
                    normalized_name="team liquid",
                    provider="raybet",
                ),
                TeamAlias(
                    canonical_team_id=spirit.id,
                    name="Team Spirit",
                    normalized_name="team spirit",
                    provider="raybet",
                ),
                ProviderTeamMapping(
                    provider="raybet",
                    provider_team_id="101",
                    canonical_team_id=liquid.id,
                    observed_name="Liquid",
                ),
                ProviderTeamMapping(
                    provider="raybet",
                    provider_team_id="202",
                    canonical_team_id=spirit.id,
                    observed_name="Team Spirit",
                ),
            )
        )
        existing_series = CanonicalSeries(
            event_id=event.id,
            team_a_id=liquid.id,
            team_b_id=spirit.id,
            scheduled_at=scheduled_at + timedelta(minutes=10),
        )
        session.add(existing_series)
        await session.flush()
        existing_series_id = existing_series.id

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
        provider_key="liquipedia-nearby-series",
    )
    async with factory.begin() as session:
        result = await projector.project_series(session, [observation])

    assert result.series_reused == 1
    assert result.series_created == 0
    async with factory() as session:
        mapping = await session.scalar(
            select(ProviderMatchMapping).where(ProviderMatchMapping.provider == "liquipedia")
        )
        assert mapping is not None
        assert mapping.canonical_series_id == existing_series_id
        canonical = await session.get(CanonicalSeries, existing_series_id)
        assert canonical is not None
        assert canonical.best_of == 3
        assert canonical.stage_key == "GROUP_STAGE"
        assert canonical.scheduled_at.replace(tzinfo=UTC) == scheduled_at
        raybet_mappings = list(
            (
                await session.scalars(
                    select(ProviderTeamMapping).where(ProviderTeamMapping.provider == "raybet")
                )
            ).all()
        )
        assert len(raybet_mappings) == 2
    await engine.dispose()
