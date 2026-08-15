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
    return _is_game_time_eligible(
        quality=snapshot.quality,
        live=snapshot.live,
        decision_at=snapshot.decision_at,
        min_game_time_seconds=min_game_time_seconds,
    )


def ai_record_is_game_time_eligible(
    canonical_payload: dict[str, Any],
    *,
    min_game_time_seconds: int,
    decision_at: datetime | None = None,
) -> bool:
    resolved_decision_at = decision_at or _payload_datetime(canonical_payload.get("decision_at"))
    quality = canonical_payload.get("quality")
    live = canonical_payload.get("live")
    return _is_game_time_eligible(
        quality=quality if isinstance(quality, dict) else {},
        live=live,
        decision_at=resolved_decision_at,
        min_game_time_seconds=min_game_time_seconds,
    )


def _is_game_time_eligible(
    *,
    quality: dict[str, Any],
    live: object,
    decision_at: datetime | None,
    min_game_time_seconds: int,
) -> bool:
    anchor_value = (quality.get("live_anchors") or {}).get("real_start_anchor")
    if decision_at is not None and isinstance(anchor_value, str):
        try:
            anchor = datetime.fromisoformat(anchor_value.replace("Z", "+00:00"))
        except ValueError:
            anchor = None
        if anchor is not None and anchor.tzinfo is not None and decision_at.tzinfo is not None:
            return (decision_at - anchor).total_seconds() >= min_game_time_seconds
    game_time = _live_game_time_seconds(live)
    return game_time is not None and game_time >= min_game_time_seconds


def _payload_datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _live_game_time_seconds(live: object) -> int | None:
    if not isinstance(live, dict):
        return None
    value = live.get("game_time_seconds")
    return value if isinstance(value, int) and not isinstance(value, bool) else None
