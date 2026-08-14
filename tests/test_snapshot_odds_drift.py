from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import Base
from app.models import OddsObservationRecord
from app.snapshots.builder import _odds_path


def _add_odds(session, *, canonical_map_id, odds_id, team_id, price, received_at):
    session.add(
        OddsObservationRecord(
            provider_match_id=1,
            odds_id=odds_id,
            canonical_map_id=canonical_map_id,
            market_type="Winner",
            match_stage="r1",
            selection_team_id=team_id,
            price=price,
            implied_probability=0.5,
            received_at=received_at,
            raw_event_id=uuid4(),
        )
    )


@pytest.mark.asyncio
async def test_odds_path_keeps_first_anchor_and_current_points_and_full_history_drift() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    canonical_map_id = uuid4()
    team_a_id = uuid4()
    team_b_id = uuid4()
    decision_at = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)
    async with factory.begin() as session:
        # 20 distinct changes in the first ~2 minutes, then one real move in
        # the final 2 minutes. The old code kept the FIRST 12 changes only, so
        # the "now" price and the 5m drift both silently described minute 1.
        received = decision_at - timedelta(minutes=20)
        for index in range(20):
            received = received + timedelta(seconds=5)
            _add_odds(
                session,
                canonical_map_id=canonical_map_id,
                odds_id=10,
                team_id=team_a_id,
                price=2.0 + index * 0.01,
                received_at=received,
            )
        _add_odds(
            session,
            canonical_map_id=canonical_map_id,
            odds_id=10,
            team_id=team_a_id,
            price=1.5,
            received_at=decision_at - timedelta(minutes=2),
        )
        _add_odds(
            session,
            canonical_map_id=canonical_map_id,
            odds_id=11,
            team_id=team_b_id,
            price=2.8,
            received_at=decision_at - timedelta(minutes=2),
        )

    async with factory() as session:
        trajectory, drift = await _odds_path(
            session,
            canonical_map_id=canonical_map_id,
            expected_team_ids=(team_a_id, team_b_id),
            decision_at=decision_at,
        )

    assert trajectory is not None
    assert drift is not None
    assert len(trajectory) <= 12
    prices_a = [float(point["price_a"]) for point in trajectory]
    # first change, the 5m anchor, and the CURRENT price all survive.
    assert prices_a[0] == pytest.approx(2.0)
    assert pytest.approx(2.19) in prices_a
    assert prices_a[-1] == pytest.approx(1.5)
    # Drift is computed from the full history, not the compressed path.
    assert drift["price_a_first"] == pytest.approx(2.0)
    assert drift["price_a_now"] == pytest.approx(1.5)
    assert drift["implied_drift_pp_since_first"] == pytest.approx((1 / 1.5 - 1 / 2.0) * 100)
    assert drift["implied_drift_pp_last_5m"] == pytest.approx((1 / 1.5 - 1 / 2.19) * 100)
    assert drift["direction"] == "SHORTENED"
    # 20 early changes + the late Team A move + the first Team B observation.
    assert drift["points"] == 22
    await engine.dispose()


@pytest.mark.asyncio
async def test_odds_path_returns_none_without_two_distinct_changes() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    canonical_map_id = uuid4()
    team_a_id = uuid4()
    team_b_id = uuid4()
    decision_at = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)
    async with factory.begin() as session:
        _add_odds(
            session,
            canonical_map_id=canonical_map_id,
            odds_id=10,
            team_id=team_a_id,
            price=2.0,
            received_at=decision_at - timedelta(minutes=1),
        )

    async with factory() as session:
        trajectory, drift = await _odds_path(
            session,
            canonical_map_id=canonical_map_id,
            expected_team_ids=(team_a_id, team_b_id),
            decision_at=decision_at,
        )
    assert trajectory is None
    assert drift is None
    await engine.dispose()
