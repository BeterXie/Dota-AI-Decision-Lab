from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.ai.eligibility import ai_decision_is_game_time_eligible
from app.domain.snapshot import DecisionSnapshot


def _snapshot(quality: dict, live: dict | None) -> DecisionSnapshot:
    decision_at = datetime(2026, 8, 14, 3, 3, 15, tzinfo=UTC)
    return DecisionSnapshot(
        snapshot_id=uuid4(),
        decision_at=decision_at,
        created_at=decision_at,
        mode="LIVE_BASIC",
        identity={},
        market={},
        draft=None,
        history={},
        live=live,
        quality=quality,
        snapshot_hash="fixture-hash",
    )


def test_real_time_anchor_gates_eligibility() -> None:
    decision_at = datetime(2026, 8, 14, 3, 3, 15, tzinfo=UTC)
    anchor = (decision_at - timedelta(minutes=11)).isoformat()
    snapshot = _snapshot(
        {"live_anchors": {"real_start_anchor": anchor, "data_lag_seconds": 900.0}},
        live={"game_time_seconds": 0},
    )

    # Real elapsed 11 minutes >= 10 even though the broadcast clock is still 0.
    assert ai_decision_is_game_time_eligible(snapshot, min_game_time_seconds=600) is True


def test_real_time_anchor_below_threshold_is_not_eligible() -> None:
    decision_at = datetime(2026, 8, 14, 3, 3, 15, tzinfo=UTC)
    anchor = (decision_at - timedelta(minutes=5)).isoformat()
    snapshot = _snapshot(
        {"live_anchors": {"real_start_anchor": anchor, "data_lag_seconds": None}},
        live={"game_time_seconds": 800},
    )

    # Real elapsed only 5 minutes: not eligible despite broadcast game time.
    assert ai_decision_is_game_time_eligible(snapshot, min_game_time_seconds=600) is False


def test_falls_back_to_broadcast_game_time_without_anchor() -> None:
    assert (
        ai_decision_is_game_time_eligible(
            _snapshot({}, live={"game_time_seconds": 700}), min_game_time_seconds=600
        )
        is True
    )
    assert (
        ai_decision_is_game_time_eligible(
            _snapshot({}, live={"game_time_seconds": 500}), min_game_time_seconds=600
        )
        is False
    )
