from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import Base
from app.history.builder import HistoricalFeatureBuilder
from app.history.scoring import beta_adjusted_win_rate
from app.history.service import HistoricalIntelligenceService
from app.models import (
    CanonicalMap,
    CanonicalPlayer,
    CanonicalSeries,
    CanonicalTeam,
    HistoricalMapRecord,
    HistoricalPlayerMapRecord,
    RoleMetricBaselineRecord,
    TeamRatingSnapshotRecord,
)


@pytest.mark.asyncio
async def test_historical_features_are_role_adjusted_append_only_and_as_of_aware() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    base = datetime(2026, 1, 1, tzinfo=UTC)

    async with factory() as session, session.begin():
        team_a = CanonicalTeam(name="A")
        team_b = CanonicalTeam(name="B")
        support = CanonicalPlayer(account_id=1001, name="Support")
        carry = CanonicalPlayer(account_id=1002, name="Carry")
        session.add_all([team_a, team_b, support, carry])
        await session.flush()
        series = CanonicalSeries(team_a_id=team_a.id, team_b_id=team_b.id)
        session.add(series)
        await session.flush()

        facts: list[HistoricalMapRecord] = []
        for index, (winner, support_gpm, carry_gpm) in enumerate(
            ((team_a.id, 300.0, 900.0), (team_b.id, 320.0, 1000.0)), start=1
        ):
            canonical_map = CanonicalMap(
                series_id=series.id,
                map_number=index,
                valve_match_id=9000 + index,
                scheduled_at=base + timedelta(hours=index),
            )
            session.add(canonical_map)
            await session.flush()
            fact = HistoricalMapRecord(
                canonical_map_id=canonical_map.id,
                provider="stratz",
                provider_match_id=str(9000 + index),
                patch_id="61",
                started_at=base + timedelta(hours=index),
                ended_at=base + timedelta(hours=index, minutes=40),
                radiant_team_id=team_a.id,
                dire_team_id=team_b.id,
                winner_team_id=winner,
                first_usable_at=base + timedelta(hours=index, minutes=41),
                fetched_at=base + timedelta(hours=index, minutes=41),
                normalizer_version="fixture",
                basic_ready_at=base + timedelta(hours=index, minutes=41),
                advanced_ready_at=base + timedelta(hours=index, minutes=45),
                sync_status="ADVANCED_READY",
                raw_event_id=canonical_map.id,
            )
            session.add(fact)
            await session.flush()
            facts.append(fact)
            session.add_all(
                [
                    HistoricalPlayerMapRecord(
                        historical_map_id=fact.id,
                        canonical_player_id=support.id,
                        account_id=1001,
                        canonical_team_id=team_a.id,
                        opponent_team_id=team_b.id,
                        hero_id=20,
                        position=5,
                        won=winner == team_a.id,
                        kills=1,
                        deaths=5 + index,
                        assists=15 + index,
                        gpm=support_gpm,
                        xpm=400.0 + index * 10,
                        networth=10000.0 + index * 100,
                        last_hits=40 + index,
                        hero_damage=9000.0 + index * 200,
                        tower_damage=100.0 * index,
                        impact=-5.0 + index,
                        basic_first_usable_at=fact.first_usable_at,
                        advanced_first_usable_at=fact.advanced_ready_at,
                    ),
                    HistoricalPlayerMapRecord(
                        historical_map_id=fact.id,
                        canonical_player_id=carry.id,
                        account_id=1002,
                        canonical_team_id=team_a.id,
                        opponent_team_id=team_b.id,
                        hero_id=10,
                        position=1,
                        won=winner == team_a.id,
                        kills=10,
                        deaths=1,
                        assists=8,
                        gpm=carry_gpm,
                        xpm=950.0,
                        networth=30000.0,
                        last_hits=500,
                        hero_damage=40000.0,
                        tower_damage=8000.0,
                        impact=30.0,
                        basic_first_usable_at=fact.first_usable_at,
                        advanced_first_usable_at=fact.advanced_ready_at,
                    ),
                ]
            )

        cutoff = base + timedelta(hours=4)
        builder = HistoricalFeatureBuilder(initial_elo=1500.0, elo_k=24.0)
        assert await builder.build_team_ratings(session, as_of=cutoff) == 4
        assert await builder.build_team_ratings(session, as_of=cutoff) == 0
        await builder.build_role_baselines(session, as_of=cutoff)
        player_form = await builder.build_player_form(
            session,
            canonical_player_id=support.id,
            position=5,
            as_of=cutoff,
        )
        player_hero = await builder.build_player_hero(
            session,
            canonical_player_id=support.id,
            hero_id=20,
            position=5,
            as_of=cutoff,
        )

        support_gpm_baseline = await session.scalar(
            select(RoleMetricBaselineRecord).where(
                RoleMetricBaselineRecord.patch_id == "61",
                RoleMetricBaselineRecord.position == 5,
                RoleMetricBaselineRecord.metric == "gpm",
            )
        )
        assert support_gpm_baseline is not None
        assert support_gpm_baseline.mean == 310.0
        assert player_form is not None
        assert player_form.sample_size == 2
        assert player_hero is not None
        assert player_hero.historical_win_rate == 0.5
        assert player_hero.adjusted_strength is not None
        assert beta_adjusted_win_rate(3, 3) < 1.0

        ratings_count = await session.scalar(
            select(func.count()).select_from(TeamRatingSnapshotRecord)
        )
        assert ratings_count == 4
        between_maps = await HistoricalIntelligenceService().get_team_payload(
            session,
            team_a.id,
            as_of=base + timedelta(hours=2, minutes=30),
        )
        assert between_maps["base_rating"] is not None
        assert between_maps["base_rating"] > 1500.0

    await engine.dispose()
