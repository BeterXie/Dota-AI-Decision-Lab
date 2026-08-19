from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import Base
from app.domain.identity import ProviderMatch
from app.identity.aliases import equivalent_team_aliases
from app.identity.resolver import IdentityAmbiguousError, IdentityResolver
from app.models import CanonicalEvent, CanonicalMap, CanonicalSeries, ProviderMatchMapping
from app.providers.dltv.models import DltvBootstrapIdentity
from app.providers.liquipedia.models import LiquipediaSeriesObservation
from app.providers.liquipedia.projection import LiquipediaCanonicalProjector


@pytest.mark.parametrize(
    ("left", "right"),
    (
        ("Liquid", "Team Liquid"),
        ("VG", "Vici Gaming"),
        ("Spirit", "Team Spirit"),
        ("LGD", "LGD Gaming"),
        ("Aurora", "Aurora.1xBet"),
        ("Level Up", "Level UP esports"),
    ),
)
def test_verified_tournament_team_aliases_share_one_group(left: str, right: str) -> None:
    assert equivalent_team_aliases(left) == equivalent_team_aliases(right)


@pytest.mark.asyncio
async def test_dltv_without_liquipedia_identity_does_not_create_an_event_or_series() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    started_at = datetime(2026, 8, 13, 5, 0, tzinfo=UTC)

    with pytest.raises(IdentityAmbiguousError, match="DLTV_LIQUIPEDIA_SERIES_REQUIRED"):
        async with factory.begin() as session:
            await IdentityResolver().resolve_dltv_bootstrap(
                session,
                DltvBootstrapIdentity(
                    valve_match_id=8943091110,
                    series_id=427640,
                    event_id=6617,
                    first_team_id=7,
                    first_team_name="Team Liquid",
                    second_team_id=3,
                    second_team_name="Vici Gaming",
                    started_at=started_at,
                    map_number=1,
                ),
            )

    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(CanonicalEvent)) == 0
        assert await session.scalar(select(func.count()).select_from(CanonicalSeries)) == 0
        assert await session.scalar(select(func.count()).select_from(CanonicalMap)) == 0
        assert await session.scalar(select(func.count()).select_from(ProviderMatchMapping)) == 0
    await engine.dispose()


@pytest.mark.asyncio
async def test_raybet_and_dltv_team_aliases_resolve_to_one_series() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    resolver = IdentityResolver()
    started_at = datetime(2026, 8, 13, 5, 0, tzinfo=UTC)

    async with factory() as session, session.begin():
        await LiquipediaCanonicalProjector().project_series(
            session,
            [
                LiquipediaSeriesObservation(
                    team_a_name="Team Liquid",
                    team_a_page="Team Liquid",
                    team_b_name="Vici Gaming",
                    team_b_page="Vici Gaming",
                    tournament_name="The International 2026",
                    tournament_page="The International/2026",
                    stage="Group Stage",
                    best_of=3,
                    scheduled_at=started_at,
                    state="UPCOMING",
                    provider_key="Match:TI2026-Liquid-VG",
                )
            ],
        )
        raybet_series_id = await resolver.observe_raybet_match(
            session,
            ProviderMatch(
                provider_match_id=38423263,
                game_id=151,
                tournament_id=1,
                tournament_name="TI15",
                team_a_id=16129,
                team_a_name="Liquid",
                team_b_id=16236,
                team_b_name="VG",
                round="bo3",
                provider_status=1,
                scheduled_at=started_at,
                observed_at=started_at,
            ),
        )
        resolved = await resolver.resolve_dltv_bootstrap(
            session,
            DltvBootstrapIdentity(
                valve_match_id=8943091110,
                series_id=427640,
                event_id=1,
                first_team_id=7,
                first_team_name="Team Liquid",
                second_team_id=3,
                second_team_name="Vici Gaming",
                started_at=started_at,
                map_number=1,
            ),
        )
        series = await session.get(CanonicalSeries, raybet_series_id)

    assert resolved.canonical_series_id == raybet_series_id
    assert series is not None
    assert resolved.team_a_id == series.team_a_id
    assert resolved.team_b_id == series.team_b_id
    await engine.dispose()
