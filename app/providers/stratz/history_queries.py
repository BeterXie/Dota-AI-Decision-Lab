from datetime import UTC, datetime, timedelta
from typing import Any

from app.domain.history import HistoricalMap, HistoricalMatchBundle, PlayerHistoricalMap

NORMALIZER_VERSION = "stratz-match-v2"

TEAM_MATCHES_QUERY = """
query HistoricalTeamMatches($teamId: Int!, $take: Int!, $skip: Int!) {
  team(teamId: $teamId) {
    matches(request: { take: $take, skip: $skip }) {
      id
      startDateTime
    }
  }
}
"""

TEAM_IDENTITY_QUERY = """
query HistoricalTeamIdentity($teamIds: [Int!]!) {
  teams(teamIds: $teamIds) {
    id
    name
  }
}
"""

MATCH_QUERY = """
query HistoricalMatch($matchId: Long!) {
  match(id: $matchId) {
    id
    startDateTime
    durationSeconds
    didRadiantWin
    radiantTeamId
    direTeamId
    radiantTeam { name }
    direTeam { name }
    gameVersionId
    league { id name }
    players {
      steamAccountId
      heroId
      position
      isRadiant
      kills
      deaths
      assists
      goldPerMinute
      experiencePerMinute
      numLastHits
      heroDamage
      towerDamage
      networth
      imp
    }
  }
}
"""


def normalize_match(payload: dict[str, Any], *, fetched_at: datetime) -> HistoricalMatchBundle:
    data = payload.get("data")
    match = data.get("match") if isinstance(data, dict) else None
    if not isinstance(match, dict):
        raise ValueError("STRATZ match payload is missing data.match")
    match_id = _int(match.get("id"))
    started_at = _datetime(match.get("startDateTime"))
    if match_id is None or started_at is None:
        raise ValueError("STRATZ match identity/time is incomplete")
    duration = _int(match.get("durationSeconds"))
    radiant_team = _id(match.get("radiantTeamId"))
    dire_team = _id(match.get("direTeamId"))
    radiant_win = match.get("didRadiantWin")
    winner = None
    if isinstance(radiant_win, bool):
        winner = radiant_team if radiant_win else dire_team
    league = match.get("league") if isinstance(match.get("league"), dict) else {}
    normalized_match = HistoricalMap(
        provider_match_id=str(match_id),
        event_id=_id(league.get("id")),
        event_name=league.get("name") if isinstance(league.get("name"), str) else None,
        patch_id=_id(match.get("gameVersionId")),
        started_at=started_at,
        ended_at=(started_at + timedelta(seconds=duration) if duration is not None else None),
        radiant_team_id=radiant_team,
        dire_team_id=dire_team,
        winner_team_id=winner,
        duration_seconds=duration,
        provider="stratz",
        first_usable_at=fetched_at,
        fetched_at=fetched_at,
    )
    players: list[PlayerHistoricalMap] = []
    warnings: list[str] = []
    for item in match.get("players", []):
        if not isinstance(item, dict):
            warnings.append("HISTORICAL_PLAYER_PAYLOAD_INVALID")
            continue
        account_id = _bounded_int(item.get("steamAccountId"), maximum=9_223_372_036_854_775_807)
        hero_id = _int(item.get("heroId"))
        is_radiant = item.get("isRadiant")
        if account_id is None or hero_id is None or not isinstance(is_radiant, bool):
            warnings.append("HISTORICAL_PLAYER_IDENTITY_PARTIAL")
            continue
        if not isinstance(radiant_win, bool):
            warnings.append("HISTORICAL_RESULT_UNKNOWN")
            continue
        stats = item.get("stats") if isinstance(item.get("stats"), dict) else {}
        players.append(
            PlayerHistoricalMap(
                provider_match_id=str(match_id),
                account_id=account_id,
                team_id=radiant_team if is_radiant else dire_team,
                opponent_team_id=dire_team if is_radiant else radiant_team,
                hero_id=hero_id,
                position=_position(item.get("position")),
                patch_id=_id(match.get("gameVersionId")),
                started_at=started_at,
                first_usable_at=fetched_at,
                won=radiant_win == is_radiant,
                kills=_int(item.get("kills")),
                deaths=_int(item.get("deaths")),
                assists=_int(item.get("assists")),
                gpm=_float(item.get("goldPerMinute")),
                xpm=_float(item.get("experiencePerMinute")),
                last_hits=_int(item.get("numLastHits")),
                hero_damage=_float(item.get("heroDamage")),
                tower_damage=_float(item.get("towerDamage")),
                networth=_float(item.get("networth")),
                impact=_float(item.get("imp"))
                if item.get("imp") is not None
                else _float(stats.get("imp")),
            )
        )
    advanced = bool(players) and any(
        player.gpm is not None or player.impact is not None for player in players
    )
    return HistoricalMatchBundle(
        match=normalized_match,
        players=tuple(players),
        advanced_available=advanced,
        warnings=tuple(dict.fromkeys(warnings)),
    )


def team_match_ids(payload: dict[str, Any], *, before: datetime, limit: int) -> list[int]:
    data = payload.get("data")
    team = data.get("team") if isinstance(data, dict) else None
    matches = team.get("matches") if isinstance(team, dict) else None
    if not isinstance(matches, list):
        raise ValueError("STRATZ team matches payload is invalid")
    result: list[int] = []
    for item in matches:
        if not isinstance(item, dict):
            continue
        match_id = _int(item.get("id"))
        started_at = _datetime(item.get("startDateTime"))
        if match_id is not None and started_at is not None and started_at < before:
            result.append(match_id)
        if len(result) >= limit:
            break
    return result


def _datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, int):
        return datetime.fromtimestamp(value, tz=UTC)
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    return None


def _int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _bounded_int(value: object, *, maximum: int) -> int | None:
    parsed = _int(value)
    return parsed if parsed is not None and abs(parsed) <= maximum else None


def _float(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _id(value: object) -> str | None:
    parsed = _int(value)
    return str(parsed) if parsed is not None else None


def _position(value: object) -> int | None:
    parsed = _int(value)
    return parsed if parsed in {1, 2, 3, 4, 5} else None
