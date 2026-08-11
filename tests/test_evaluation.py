from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import Base
from app.evaluation.future_odds import FutureOddsService
from app.evaluation.metrics import brier_score, log_loss
from app.evaluation.settlement import SettlementService
from app.jobs.repository import JobRepository
from app.models import CanonicalMap, CanonicalSeries, CanonicalTeam, OddsObservationRecord
from app.snapshots.repository import SnapshotRepository


def test_missing_probability_stays_missing_in_scoring() -> None:
    assert brier_score(None, True) is None
    assert log_loss(None, False) is None
    assert brier_score(0.7, True) == pytest.approx(0.09)


@pytest.mark.asyncio
async def test_future_odds_capture_uses_first_observation_after_due_time() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    decision_at = datetime(2026, 1, 1, tzinfo=UTC)
    due_at = decision_at + timedelta(seconds=30)

    async with factory() as session, session.begin():
        snapshot = await SnapshotRepository().persist(
            session,
            canonical_map_id=None,
            decision_at=decision_at,
            mode="PREMATCH",
            identity={},
            market={
                "observations": [
                    {"odds_id": 10, "price": "2.00"},
                    {"odds_id": 20, "price": "2.00"},
                ]
            },
            draft=None,
            history={},
            live=None,
            quality={"eligible": True},
        )
        for odds_id, price, seconds in (
            (10, "1.90", 31),
            (20, "2.10", 32),
            (10, "1.70", 50),
            (20, "2.30", 50),
        ):
            session.add(
                OddsObservationRecord(
                    provider_match_id=1,
                    odds_id=odds_id,
                    price=Decimal(price),
                    implied_probability=1 / float(price),
                    received_at=decision_at + timedelta(seconds=seconds),
                    raw_event_id=uuid4(),
                )
            )
        captured = await FutureOddsService(JobRepository()).capture(
            session,
            snapshot_id=snapshot.snapshot_id,
            horizon_seconds=30,
            due_at=due_at,
            observed_at=decision_at + timedelta(seconds=60),
        )

        assert captured.status == "CAPTURED"
        assert captured.odds_a == Decimal("1.90")
        assert captured.odds_b == Decimal("2.10")

    await engine.dispose()


@pytest.mark.asyncio
async def test_conflicting_settlement_has_no_winner() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime(2026, 1, 1, tzinfo=UTC)

    async with factory() as session, session.begin():
        team_a = CanonicalTeam(name="A")
        team_b = CanonicalTeam(name="B")
        session.add_all([team_a, team_b])
        await session.flush()
        series = CanonicalSeries(team_a_id=team_a.id, team_b_id=team_b.id)
        session.add(series)
        await session.flush()
        canonical_map = CanonicalMap(series_id=series.id, map_number=1)
        session.add(canonical_map)
        await session.flush()
        service = SettlementService()
        await service.settle(
            session,
            canonical_map_id=canonical_map.id,
            winner_team_id=team_a.id,
            basic_first_usable_at=now,
        )
        record = await service.settle(
            session,
            canonical_map_id=canonical_map.id,
            winner_team_id=team_b.id,
            basic_first_usable_at=now + timedelta(seconds=1),
        )

        assert record.provider_conflict is True
        assert record.winner_team_id is None

    await engine.dispose()
