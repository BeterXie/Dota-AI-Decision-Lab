from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.temporal.aligner import CalibrationSignal, estimate_synchronization


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
    assert estimate.status == "UNKNOWN"
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
