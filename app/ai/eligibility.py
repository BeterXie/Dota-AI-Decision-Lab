from datetime import datetime
from typing import Any

from app.domain.snapshot import DecisionSnapshot


def ai_decision_live_game_time(snapshot: DecisionSnapshot) -> int | None:
    return _live_game_time_seconds(snapshot.live)


def ai_record_live_game_time(canonical_payload: dict[str, Any]) -> int | None:
    live = canonical_payload.get("live")
    return _live_game_time_seconds(live)


def ai_decision_is_game_time_eligible(
    snapshot: DecisionSnapshot, *, min_game_time_seconds: int
) -> bool:
    """Decision eligibility on REAL elapsed time when the start anchor exists.

    The anchor is the series scheduled start (stored in snapshot quality
    live_anchors): DLTV broadcasts lag the real game, so the broadcast game
    clock cannot schedule decisions on real time.  When the anchor is known,
    eligibility uses real elapsed time since the scheduled start; otherwise it
    falls back to the broadcast game clock.
    """
    anchor_value = (snapshot.quality.get("live_anchors") or {}).get("real_start_anchor")
    if isinstance(anchor_value, str):
        try:
            anchor = datetime.fromisoformat(anchor_value.replace("Z", "+00:00"))
        except ValueError:
            anchor = None
        if anchor is not None and anchor.tzinfo is not None:
            elapsed = (snapshot.decision_at - anchor).total_seconds()
            return elapsed >= min_game_time_seconds
    game_time = ai_decision_live_game_time(snapshot)
    return game_time is not None and game_time >= min_game_time_seconds


def ai_record_is_game_time_eligible(
    canonical_payload: dict[str, Any], *, min_game_time_seconds: int
) -> bool:
    game_time = ai_record_live_game_time(canonical_payload)
    return game_time is not None and game_time >= min_game_time_seconds


def _live_game_time_seconds(live: object) -> int | None:
    if not isinstance(live, dict):
        return None
    value = live.get("game_time_seconds")
    return value if isinstance(value, int) and not isinstance(value, bool) else None
