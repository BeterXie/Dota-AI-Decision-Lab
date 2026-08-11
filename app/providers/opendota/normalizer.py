from datetime import UTC, datetime, timedelta
from typing import Any

from app.domain.history import HistoricalMap, HistoricalMatchBundle, PlayerHistoricalMap

NORMALIZER_VERSION = "opendota-match-v1"


def normalize_match(payload: dict[str, Any], *, fetched_at: datetime) -> HistoricalMatchBundle:
    match_id = _required_int(payload, "match_id")
    start_time = _required_int(payload, "start_time")
    started_at = datetime.fromtimestamp(start_time, tz=UTC)
    duration = _optional_int(payload.get("duration"))
    radiant_team = _optional_id(payload.get("radiant_team_id"))
    dire_team = _optional_id(payload.get("dire_team_id"))
    radiant_win = payload.get("radiant_win")
    winner_team = None
    if isinstance(radiant_win, bool):
        winner_team = radiant_team if radiant_win else dire_team
    league = payload.get("league") if isinstance(payload.get("league"), dict) else {}
    event_name = league.get("name") or payload.get("league_name")
    event_id = _optional_id(payload.get("leagueid"))
    match = HistoricalMap(
        provider_match_id=str(match_id),
        event_id=event_id,
        event_name=event_name if isinstance(event_name, str) else None,
        patch_id=_optional_id(payload.get("patch")),
        started_at=started_at,
        ended_at=(started_at + timedelta(seconds=duration) if duration is not None else None),
        radiant_team_id=radiant_team,
        dire_team_id=dire_team,
        winner_team_id=winner_team,
        duration_seconds=duration,
        provider="opendota",
        first_usable_at=fetched_at,
        fetched_at=fetched_at,
    )

    players: list[PlayerHistoricalMap] = []
    warnings: list[str] = []
    raw_players = payload.get("players")
    if isinstance(raw_players, list):
        for item in raw_players:
            if not isinstance(item, dict):
                warnings.append("HISTORICAL_PLAYER_PAYLOAD_INVALID")
                continue
            account_id = _optional_int(item.get("account_id"))
            hero_id = _optional_int(item.get("hero_id"))
            is_radiant = _is_radiant(item)
            if account_id is None or hero_id is None or is_radiant is None:
                warnings.append("HISTORICAL_PLAYER_IDENTITY_PARTIAL")
                continue
            won = _won(item, is_radiant=is_radiant, radiant_win=radiant_win)
            if won is None:
                warnings.append("HISTORICAL_RESULT_UNKNOWN")
                continue
            players.append(
                PlayerHistoricalMap(
                    provider_match_id=str(match_id),
                    account_id=account_id,
                    team_id=radiant_team if is_radiant else dire_team,
                    opponent_team_id=dire_team if is_radiant else radiant_team,
                    hero_id=hero_id,
                    position=_position(item.get("position_est")),
                    patch_id=_optional_id(payload.get("patch")),
                    started_at=started_at,
                    first_usable_at=fetched_at,
                    won=won,
                    kills=_optional_int(item.get("kills")),
                    deaths=_optional_int(item.get("deaths")),
                    assists=_optional_int(item.get("assists")),
                    gpm=_optional_float(item.get("gold_per_min")),
                    xpm=_optional_float(item.get("xp_per_min")),
                    last_hits=_optional_int(item.get("last_hits")),
                    hero_damage=_optional_float(item.get("hero_damage")),
                    tower_damage=_optional_float(item.get("tower_damage")),
                    networth=_optional_float(item.get("total_gold")),
                    impact=None,
                )
            )
    advanced = bool(players) and any(
        player.gpm is not None or player.impact is not None for player in players
    )
    return HistoricalMatchBundle(
        match=match,
        players=tuple(players),
        advanced_available=advanced,
        warnings=tuple(dict.fromkeys(warnings)),
    )


def _required_int(payload: dict[str, Any], key: str) -> int:
    value = _optional_int(payload.get(key))
    if value is None:
        raise ValueError(f"OpenDota match field {key} is required")
    return value


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _optional_float(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _optional_id(value: object) -> str | None:
    parsed = _optional_int(value)
    return str(parsed) if parsed is not None else None


def _position(value: object) -> int | None:
    parsed = _optional_int(value)
    return parsed if parsed in {1, 2, 3, 4, 5} else None


def _is_radiant(player: dict[str, Any]) -> bool | None:
    value = player.get("isRadiant", player.get("is_radiant"))
    if isinstance(value, bool):
        return value
    slot = _optional_int(player.get("player_slot"))
    return slot < 128 if slot is not None else None


def _won(player: dict[str, Any], *, is_radiant: bool, radiant_win: object) -> bool | None:
    win = player.get("win")
    if win in {0, 1}:
        return bool(win)
    if isinstance(radiant_win, bool):
        return radiant_win == is_radiant
    return None
