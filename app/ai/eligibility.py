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
