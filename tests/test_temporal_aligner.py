from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.db import Base
from app.models import LiveSyncEstimateRecord
from app.temporal.aligner import CalibrationSignal, TemporalAligner, estimate_synchronization


def _signals(base: datetime, offsets: tuple[float, ...]) -> list[CalibrationSignal]:
    return [CalibrationSignal(base + timedelta(seconds=offset), "TEST") for offset in offsets]


def test_sync_requires_multiple_calibration_events() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    estimate = estimate_synchronization(
        uuid4(),
        _signals(now, (0, 10)),
        _signals(now, (1, 11)),
        calculated_at=now,
        pairing_window_seconds=30,
        safe_seconds=3,
        caution_seconds=8,
        min_samples=3,
    )

    assert estimate.sample_size == 2
    assert estimate.status == "CALIBRATING"
    assert estimate.confidence == "LOW"


def test_sync_uses_p90_for_safety_status() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    estimate = estimate_synchronization(
        uuid4(),
        _signals(now, (0, 10, 20, 30)),
        _signals(now, (1, 12, 23, 34)),
        calculated_at=now,
        pairing_window_seconds=30,
        safe_seconds=3,
        caution_seconds=8,
        min_samples=3,
    )

    assert estimate.estimated_lag_seconds == 2.5
    assert estimate.p50_seconds == 2.5
    assert estimate.p90_seconds == 4
    assert estimate.status == "CAUTION"


def test_nearest_but_ambiguous_pair_is_rejected() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    estimate = estimate_synchronization(
        uuid4(),
        _signals(now, (0,)),
        _signals(now, (1.0, 1.2)),
        calculated_at=now,
        pairing_window_seconds=30,
        safe_seconds=3,
        caution_seconds=8,
        min_samples=1,
        ambiguity_margin_seconds=0.5,
    )

    assert estimate.sample_size == 0
    assert estimate.status == "CALIBRATING"
    assert estimate.ambiguous_ratio == 1.0


def test_single_live_event_cannot_match_multiple_market_events() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    estimate = estimate_synchronization(
        uuid4(),
        _signals(now, (0, 0.5)),
        _signals(now, (1,)),
        calculated_at=now,
        pairing_window_seconds=30,
        safe_seconds=3,
        caution_seconds=8,
        min_samples=1,
    )

    assert estimate.sample_size == 1
    assert estimate.accepted_pair_ratio == 0.5
    assert estimate.status == "CALIBRATING"


def test_high_jitter_never_becomes_safe() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    estimate = estimate_synchronization(
        uuid4(),
        _signals(now, (0, 10, 20, 30)),
        _signals(now, (0.1, 15, 20.2, 35)),
        calculated_at=now,
        pairing_window_seconds=8,
        safe_seconds=3,
        caution_seconds=8,
        min_samples=3,
    )

    assert estimate.jitter_seconds is not None
    assert estimate.status != "SAFE"


@pytest.mark.asyncio
async def test_calculate_reuses_existing_estimate_for_same_checkpoint() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    map_id = uuid4()
    calculated_at = datetime(2026, 8, 13, 8, 0, tzinfo=UTC)

    async with factory() as session, session.begin():
        aligner = TemporalAligner(Settings())
        first = await aligner.calculate(
            session,
            canonical_map_id=map_id,
            as_of=calculated_at,
        )
        await session.flush()
        second = await aligner.calculate(
            session,
            canonical_map_id=map_id,
            as_of=calculated_at,
        )
        count = await session.scalar(select(func.count()).select_from(LiveSyncEstimateRecord))

    assert second == first
    assert count == 1
    await engine.dispose()
