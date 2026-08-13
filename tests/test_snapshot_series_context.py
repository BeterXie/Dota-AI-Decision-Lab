from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import Base
from app.models import CanonicalMap, CanonicalSeries, CanonicalTeam, MapResultRecord
from app.snapshots.side_aware import _series_score


@pytest.mark.asyncio
async def test_series_score_only_uses_results_available_by_decision_time() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    start = datetime(2026, 8, 14, 0, 0, tzinfo=UTC)

    async with factory() as session, session.begin():
        team_a = CanonicalTeam(name="A")
        team_b = CanonicalTeam(name="B")
        session.add_all((team_a, team_b))
        await session.flush()
        series = CanonicalSeries(team_a_id=team_a.id, team_b_id=team_b.id, best_of=3)
        session.add(series)
        await session.flush()
        map_1 = CanonicalMap(series_id=series.id, map_number=1)
        map_2 = CanonicalMap(series_id=series.id, map_number=2)
        session.add_all((map_1, map_2))
        await session.flush()
        session.add_all(
            (
                MapResultRecord(
                    canonical_map_id=map_1.id,
                    winner_team_id=team_a.id,
                    basic_first_usable_at=start + timedelta(minutes=50),
                ),
                MapResultRecord(
                    canonical_map_id=map_2.id,
                    winner_team_id=team_b.id,
                    basic_first_usable_at=start + timedelta(minutes=110),
                ),
            )
        )

    async with factory() as session:
        series = await session.get(CanonicalSeries, series.id)
        assert series is not None
        score = await _series_score(
            session,
            series=series,
            decision_at=start + timedelta(minutes=80),
        )

    assert score[0] == 1
    assert score[1] == 0
    assert score[2] == start + timedelta(minutes=50)
    await engine.dispose()
