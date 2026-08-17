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
        team_a = CanonicalTeam(name="Future A")
        team_b = CanonicalTeam(name="Future B")
        session.add_all([team_a, team_b])
        await session.flush()
        series = CanonicalSeries(team_a_id=team_a.id, team_b_id=team_b.id)
        session.add(series)
        await session.flush()
        snapshot = await SnapshotRepository().persist(
            session,
            canonical_map_id=None,
            decision_at=decision_at,
            mode="PREMATCH",
            identity={
                "series_id": str(series.id),
                "map_id": None,
                "team_a": {"id": str(team_a.id)},
                "team_b": {"id": str(team_b.id)},
            },
            market={
                "provider_match_id": 1,
                "market_type": "match_winner",
                "match_stage": "Map 1",
                "observations": [
                    {"odds_id": 10, "selection_team_id": str(team_a.id), "price": "2.00"},
                    {"odds_id": 20, "selection_team_id": str(team_b.id), "price": "2.00"},
                ],
            },
            draft=None,
            history={},
            live=None,
            quality={"eligible": True},
        )
        for odds_id, price, seconds, team_id in (
            (10, "1.90", 31, team_a.id),
            (20, "2.10", 32, team_b.id),
            (10, "1.70", 50, team_a.id),
            (20, "2.30", 50, team_b.id),
        ):
            session.add(
                OddsObservationRecord(
                    provider_match_id=1,
                    odds_id=odds_id,
                    canonical_series_id=series.id,
                    market_type="match_winner",
                    match_stage="Map 1",
                    selection_team_id=team_id,
                    price=Decimal(price),
                    implied_probability=1 / float(price),
                    normalized_status="OPEN_CONFIRMED",
                    metadata_version="registry-v1",
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
        assert captured.pair_quality["eligible"] is True

    await engine.dispose()


@pytest.mark.asyncio
async def test_closing_capture_is_explicit_and_uses_same_market_pair() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    started_at = datetime(2026, 1, 1, tzinfo=UTC)
    decision_at = started_at - timedelta(seconds=1)

    async with factory() as session, session.begin():
        team_a = CanonicalTeam(name="A")
        team_b = CanonicalTeam(name="B")
        session.add_all([team_a, team_b])
        await session.flush()
        series = CanonicalSeries(team_a_id=team_a.id, team_b_id=team_b.id)
        session.add(series)
        await session.flush()
        snapshot = await SnapshotRepository().persist(
            session,
            canonical_map_id=None,
            decision_at=decision_at,
            mode="PREMATCH",
            identity={
                "series_id": str(series.id),
                "map_id": None,
                "team_a": {"id": str(team_a.id)},
                "team_b": {"id": str(team_b.id)},
            },
            market={
                "provider_match_id": 1,
                "market_type": "match_winner",
                "match_stage": "Map 1",
                "observations": [
                    {"odds_id": 10, "price": "2.00"},
                    {"odds_id": 20, "price": "2.00"},
                ],
            },
            draft=None,
            history={},
            live=None,
            quality={"eligible": True},
        )
        for odds_id, price, team_id in (
            (10, "1.80", team_a.id),
            (20, "2.20", team_b.id),
        ):
            session.add(
                OddsObservationRecord(
                    provider_match_id=1,
                    odds_id=odds_id,
                    canonical_series_id=series.id,
                    market_type="match_winner",
                    match_stage="Map 1",
                    selection_team_id=team_id,
                    price=Decimal(price),
                    implied_probability=1 / float(price),
                    normalized_status="UNKNOWN",
                    metadata_version="registry-v1",
                    received_at=decision_at - timedelta(seconds=1),
                    raw_event_id=uuid4(),
                )
            )
        session.add(
            OddsObservationRecord(
                provider_match_id=1,
                odds_id=10,
                market_type="match_winner",
                match_stage="Map 2",
                price=Decimal("1.50"),
                implied_probability=1 / 1.5,
                normalized_status="UNKNOWN",
                received_at=started_at,
                raw_event_id=uuid4(),
            )
        )
        captured = await FutureOddsService(JobRepository()).capture_closing(
            session,
            snapshot_id=snapshot.snapshot_id,
            triggered_at=started_at,
        )

    assert captured.capture_type == "CLOSING"
    assert captured.horizon_seconds is None
    assert captured.capture_policy_version == "closing-policy-v1"
    assert captured.odds_a == Decimal("1.80")
    assert captured.odds_b == Decimal("2.20")
    assert captured.pair_quality["eligible"] is True
    assert captured.pair_skew_seconds == 0
    await engine.dispose()


@pytest.mark.asyncio
async def test_closing_capture_rejects_stale_or_skewed_pair() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    decision_at = datetime(2026, 1, 1, tzinfo=UTC)
    started_at = decision_at + timedelta(minutes=5)

    async with factory() as session, session.begin():
        team_a = CanonicalTeam(name="A")
        team_b = CanonicalTeam(name="B")
        session.add_all([team_a, team_b])
        await session.flush()
        series = CanonicalSeries(team_a_id=team_a.id, team_b_id=team_b.id)
        session.add(series)
        await session.flush()
        snapshot = await SnapshotRepository().persist(
            session,
            canonical_map_id=None,
            decision_at=decision_at,
            mode="PREMATCH",
            identity={
                "series_id": str(series.id),
                "map_id": None,
                "team_a": {"id": str(team_a.id)},
                "team_b": {"id": str(team_b.id)},
            },
            market={
                "provider_match_id": 1,
                "market_type": "match_winner",
                "match_stage": "Map 1",
                "observations": [{"odds_id": 10}, {"odds_id": 20}],
            },
            draft=None,
            history={},
            live=None,
            quality={"eligible": True},
        )
        for odds_id, team_id, seconds in (
            (10, team_a.id, 1),
            (20, team_b.id, 20),
        ):
            session.add(
                OddsObservationRecord(
                    provider_match_id=1,
                    odds_id=odds_id,
                    canonical_series_id=series.id,
                    market_type="match_winner",
                    match_stage="Map 1",
                    selection_team_id=team_id,
                    price=Decimal("2.00"),
                    implied_probability=0.5,
                    normalized_status="UNKNOWN",
                    metadata_version="registry-v1",
                    received_at=started_at - timedelta(seconds=seconds),
                    raw_event_id=uuid4(),
                )
            )
        captured = await FutureOddsService(JobRepository()).capture_closing(
            session,
            snapshot_id=snapshot.snapshot_id,
            triggered_at=started_at,
        )

    assert captured.status == "MISSING"
    assert captured.odds_a is None
    assert captured.odds_b is None
    assert "MARKET_PAIR_SKEW_EXCEEDED" in captured.pair_quality["blockers"]
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
            provider="stratz",
            provider_match_id="1",
            result_observed_at=now,
            basic_first_usable_at=now,
            raw_event_id=uuid4(),
            normalizer_version="fixture-v1",
            identity_confidence=1.0,
        )
        record = await service.settle(
            session,
            canonical_map_id=canonical_map.id,
            winner_team_id=team_b.id,
            provider="opendota",
            provider_match_id="1",
            result_observed_at=now + timedelta(seconds=1),
            basic_first_usable_at=now + timedelta(seconds=1),
            raw_event_id=uuid4(),
            normalizer_version="fixture-v1",
            identity_confidence=1.0,
        )

        assert record.provider_conflict is True
        assert record.winner_team_id is None

    await engine.dispose()


@pytest.mark.asyncio
async def test_missing_future_odds_can_upgrade_to_captured() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    decision_at = datetime(2026, 8, 16, tzinfo=UTC)
    due_at = decision_at + timedelta(seconds=30)
    service = FutureOddsService(JobRepository())
    async with factory() as session, session.begin():
        team_a = CanonicalTeam(name="Upgrade A")
        team_b = CanonicalTeam(name="Upgrade B")
        session.add_all([team_a, team_b])
        await session.flush()
        series = CanonicalSeries(team_a_id=team_a.id, team_b_id=team_b.id)
        session.add(series)
        await session.flush()
        snapshot = await SnapshotRepository().persist(
            session,
            canonical_map_id=None,
            decision_at=decision_at,
            mode="PREMATCH",
            identity={
                "series_id": str(series.id),
                "map_id": None,
                "team_a": {"id": str(team_a.id)},
                "team_b": {"id": str(team_b.id)},
            },
            market={
                "provider_match_id": 1,
                "market_type": "match_winner",
                "match_stage": "Map 1",
                "observations": [
                    {"odds_id": 10, "selection_team_id": str(team_a.id)},
                    {"odds_id": 20, "selection_team_id": str(team_b.id)},
                ],
            },
            draft=None,
            history={},
            live=None,
            quality={"eligible": True},
        )
        missing = await service.capture(
            session,
            snapshot_id=snapshot.snapshot_id,
            horizon_seconds=30,
            due_at=due_at,
            observed_at=due_at + timedelta(seconds=1),
        )
        assert missing.status == "MISSING"
        missing_id = missing.id
        for odds_id, price, team_id in (
            (10, "1.90", team_a.id),
            (20, "2.10", team_b.id),
        ):
            session.add(
                OddsObservationRecord(
                    provider_match_id=1,
                    odds_id=odds_id,
                    canonical_series_id=series.id,
                    market_type="match_winner",
                    match_stage="Map 1",
                    selection_team_id=team_id,
                    price=Decimal(price),
                    implied_probability=1 / float(price),
                    normalized_status="OPEN_CONFIRMED",
                    metadata_version="registry-v1",
                    received_at=due_at + timedelta(seconds=2),
                    raw_event_id=uuid4(),
                )
            )
        captured = await service.capture(
            session,
            snapshot_id=snapshot.snapshot_id,
            horizon_seconds=30,
            due_at=due_at,
            observed_at=due_at + timedelta(seconds=5),
        )
        assert captured.id == missing_id
        assert captured.status == "CAPTURED"
        assert captured.odds_a == Decimal("1.90")
        assert captured.odds_b == Decimal("2.10")
        assert captured.pair_quality["eligible"] is True
    await engine.dispose()
