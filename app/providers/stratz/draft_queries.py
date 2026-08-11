from collections.abc import Mapping, Sequence
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

REFERENCE_REPOSITORY = "BeterXie/dota2-predictor"
REFERENCE_COMMIT = "c7a54b59299fb6f46988cb85ed85ebacfe9c0f04"
QUERY_VERSION = "rosh-stratz-c7a54b5-v1"
WEEK_SECONDS = 604_800
ROSH_BRACKET = "IMMORTAL"
ROSH_BRACKET_BASIC = "DIVINE_IMMORTAL"
ROSH_PLAYER_IMPACT_CAP = 1.5


HEROES_META_POSITIONS_QUERY = """\
query HeroesMetaPositionsByWeek($bracketBasicIds: [RankBracketBasicEnum], $week: Long, $heroIds: [Short]) {
  heroStats {
    heroesPos_1: stats(positionIds: [POSITION_1], bracketBasicIds: $bracketBasicIds, week: $week, heroIds: $heroIds) { heroId matchCount winCount }
    heroesPos_2: stats(positionIds: [POSITION_2], bracketBasicIds: $bracketBasicIds, week: $week, heroIds: $heroIds) { heroId matchCount winCount }
    heroesPos_3: stats(positionIds: [POSITION_3], bracketBasicIds: $bracketBasicIds, week: $week, heroIds: $heroIds) { heroId matchCount winCount }
    heroesPos_4: stats(positionIds: [POSITION_4], bracketBasicIds: $bracketBasicIds, week: $week, heroIds: $heroIds) { heroId matchCount winCount }
    heroesPos_5: stats(positionIds: [POSITION_5], bracketBasicIds: $bracketBasicIds, week: $week, heroIds: $heroIds) { heroId matchCount winCount }
    heroes: stats(bracketBasicIds: $bracketBasicIds, week: $week, heroIds: $heroIds) { heroId matchCount winCount }
  }
}
"""

HERO_STATS_BY_TIME_QUERY = """\
query GetHeroStatsByTime($bracketBasicIds: [RankBracketBasicEnum], $week: Long, $heroIds: [Short]) {
  heroStats {
    heroStatsByTime_1: stats(bracketBasicIds: $bracketBasicIds, positionIds: [POSITION_1], groupByTime: true, minTime: 20, maxTime: 62, week: $week, heroIds: $heroIds) { heroId time winCount matchCount }
    heroStatsByTime_2: stats(bracketBasicIds: $bracketBasicIds, positionIds: [POSITION_2], groupByTime: true, minTime: 20, maxTime: 62, week: $week, heroIds: $heroIds) { heroId time winCount matchCount }
    heroStatsByTime_3: stats(bracketBasicIds: $bracketBasicIds, positionIds: [POSITION_3], groupByTime: true, minTime: 20, maxTime: 62, week: $week, heroIds: $heroIds) { heroId time winCount matchCount }
    heroStatsByTime_4: stats(bracketBasicIds: $bracketBasicIds, positionIds: [POSITION_4], groupByTime: true, minTime: 20, maxTime: 62, week: $week, heroIds: $heroIds) { heroId time winCount matchCount }
    heroStatsByTime_5: stats(bracketBasicIds: $bracketBasicIds, positionIds: [POSITION_5], groupByTime: true, minTime: 20, maxTime: 62, week: $week, heroIds: $heroIds) { heroId time winCount matchCount }
  }
}
"""

SYNERGY_QUERY = """\
query Synergy(
  $bracketBasicIds: [RankBracketBasicEnum]
  $matchLimit: Int
  $take: Int
  $currentWeek: Long!
  $previousWeek1: Long!
  $previousWeek2: Long!
  $previousWeek3: Long!
  $heroIds: [Short]
) {
  heroStats {
    matchUp_Prev_Week_1: matchUp(bracketBasicIds: $bracketBasicIds, matchLimit: $matchLimit, take: $take, week: $currentWeek, heroIds: $heroIds) { heroId vs { heroId2 synergy matchCount } with { heroId2 synergy matchCount } }
    matchUp_Prev_Week_2: matchUp(bracketBasicIds: $bracketBasicIds, matchLimit: $matchLimit, take: $take, week: $previousWeek1, heroIds: $heroIds) { heroId vs { heroId2 synergy matchCount } with { heroId2 synergy matchCount } }
    matchUp_Prev_Week_3: matchUp(bracketBasicIds: $bracketBasicIds, matchLimit: $matchLimit, take: $take, week: $previousWeek2, heroIds: $heroIds) { heroId vs { heroId2 synergy matchCount } with { heroId2 synergy matchCount } }
    matchUp_Prev_Week_4: matchUp(bracketBasicIds: $bracketBasicIds, matchLimit: $matchLimit, take: $take, week: $previousWeek3, heroIds: $heroIds) { heroId vs { heroId2 synergy matchCount } with { heroId2 synergy matchCount } }
  }
}
"""

PLAYER_HIGHLIGHT_FIELDS = """\
      lastPlayed
      winCount
      matchCount
      impAllTime
      winCountLastMonth
      matchCountLastMonth
      impLastMonth
      winCountLastSixMonths
      matchCountLastSixMonths
      impLastSixMonths"""


def build_rosh_query_requests(
    hero_ids: Sequence[int],
    week: int,
    bracket_basic_id: str = ROSH_BRACKET_BASIC,
) -> dict[str, dict[str, Any]]:
    heroes = list(dict.fromkeys(int(hero_id) for hero_id in hero_ids))
    common = {
        "bracketBasicIds": bracket_basic_id,
        "week": int(week),
        "heroIds": heroes,
    }
    return {
        "heroes_meta_positions": {
            "operation_name": "HeroesMetaPositionsByWeek",
            "query": HEROES_META_POSITIONS_QUERY,
            "variables": dict(common),
        },
        "hero_stats_by_time_bracket": {
            "operation_name": "GetHeroStatsByTime",
            "query": HERO_STATS_BY_TIME_QUERY,
            "variables": dict(common),
        },
        "synergy": {
            "operation_name": "Synergy",
            "query": SYNERGY_QUERY,
            "variables": {
                "bracketBasicIds": bracket_basic_id,
                "matchLimit": 0,
                "take": 200,
                "currentWeek": int(week),
                "previousWeek1": int(week) - WEEK_SECONDS,
                "previousWeek2": int(week) - (2 * WEEK_SECONDS),
                "previousWeek3": int(week) - (3 * WEEK_SECONDS),
                "heroIds": heroes,
            },
        },
    }


def build_player_highlights_query(players: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    definitions: list[str] = []
    rows: list[str] = []
    variables: dict[str, int] = {}
    aliases: dict[str, int] = {}
    fallback_reasons: dict[int, str] = {}
    for index, player in enumerate(players):
        account_id = player.get("steamAccountId")
        hero_id = player.get("heroId")
        if not _is_int(account_id):
            fallback_reasons[index] = "player_not_selected"
            continue
        if not _is_int(hero_id):
            fallback_reasons[index] = "hero_not_selected"
            continue
        alias = f"player_{index}"
        definitions.extend((f"${alias}SteamAccountId: Long!", f"${alias}HeroId: Short!"))
        rows.append(
            f"    {alias}: playerHeroHighlight("
            f"steamAccountId: ${alias}SteamAccountId, "
            f"heroId: ${alias}HeroId) {{\n{PLAYER_HIGHLIGHT_FIELDS}\n    }}"
        )
        variables[f"{alias}SteamAccountId"] = account_id
        variables[f"{alias}HeroId"] = hero_id
        aliases[alias] = index
    query = ""
    if rows:
        query = (
            f"query PlayerHeroHighlights({', '.join(definitions)}) {{\n"
            "  plus {\n"
            f"{'\n'.join(rows)}\n"
            "  }\n"
            "}"
        )
    return {
        "operation_name": "PlayerHeroHighlights",
        "query": query,
        "variables": variables,
        "aliases": aliases,
        "fallback_reasons": fallback_reasons,
    }


def normalize_rosh_analysis(
    responses: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    normalized: dict[str, dict[str, Any]] = {}
    for key in ("heroes_meta_positions", "hero_stats_by_time_bracket", "synergy"):
        response = responses.get(key, {})
        data = response.get("data", response)
        hero_stats = data.get("heroStats", {}) if isinstance(data, Mapping) else {}
        normalized[key] = dict(hero_stats) if isinstance(hero_stats, Mapping) else {}
    return normalized


def normalize_player_highlights_response(
    request: Mapping[str, Any], response: Mapping[str, Any]
) -> dict[int, dict[str, Any] | None]:
    data = response.get("data", response)
    plus = data.get("plus", {}) if isinstance(data, Mapping) else {}
    result: dict[int, dict[str, Any] | None] = {}
    for alias, index in request.get("aliases", {}).items():
        raw = plus.get(alias) if isinstance(plus, Mapping) else None
        result[int(index)] = (
            normalize_player_hero_highlight(raw) if isinstance(raw, Mapping) else None
        )
    return result


def normalize_player_hero_highlight(raw: Mapping[str, Any]) -> dict[str, Any]:
    match_count = max(0, _as_int(raw.get("matchCount")))
    win_count = max(0, _as_int(raw.get("winCount")))
    month_matches = max(0, _as_int(raw.get("matchCountLastMonth")))
    month_wins = max(0, _as_int(raw.get("winCountLastMonth")))
    six_month_matches = max(0, _as_int(raw.get("matchCountLastSixMonths")))
    six_month_wins = max(0, _as_int(raw.get("winCountLastSixMonths")))
    recent_window = "all_time"
    recent_matches = match_count
    recent_wins = win_count
    recent_imp = _optional_float(raw.get("impAllTime"))
    if month_matches > 0:
        recent_window = "last_month"
        recent_matches = month_matches
        recent_wins = month_wins
        recent_imp = _optional_float(raw.get("impLastMonth"))
    elif six_month_matches > 0:
        recent_window = "last_six_months"
        recent_matches = six_month_matches
        recent_wins = six_month_wins
        recent_imp = _optional_float(raw.get("impLastSixMonths"))
    return {
        "lastPlayed": _as_int(raw.get("lastPlayed")) if _is_number(raw.get("lastPlayed")) else None,
        "matchCount": match_count,
        "winCount": win_count,
        "winRate": _win_rate(win_count, match_count),
        "impAllTime": _round_optional(raw.get("impAllTime"), 2),
        "lastMonth": {
            "matchCount": month_matches,
            "winCount": month_wins,
            "winRate": _win_rate(month_wins, month_matches),
            "imp": _round_optional(raw.get("impLastMonth"), 2),
        },
        "lastSixMonths": {
            "matchCount": six_month_matches,
            "winCount": six_month_wins,
            "winRate": _win_rate(six_month_wins, six_month_matches),
            "imp": _round_optional(raw.get("impLastSixMonths"), 2),
        },
        "recentWindow": recent_window,
        "recentMatchCount": recent_matches,
        "recentWinCount": recent_wins,
        "recentWinRate": _win_rate(recent_wins, recent_matches),
        "recentImp": _php_round(recent_imp, 2) if recent_imp is not None else None,
    }


def calculate_player_impact(player_hero_stats: Mapping[str, Any] | None) -> float:
    if player_hero_stats is None:
        return 0.0
    match_count = max(0, _as_int(player_hero_stats.get("matchCount")))
    win_rate = player_hero_stats.get("winRate")
    if not _is_number(win_rate) or match_count == 0:
        return 0.0
    recent_match_count = max(0, _as_int(player_hero_stats.get("recentMatchCount")))
    recent_win_rate = player_hero_stats.get("recentWinRate")
    overall_diff = float(win_rate) - 50.0
    recent_diff = float(recent_win_rate) - 50.0 if _is_number(recent_win_rate) else overall_diff
    overall_confidence = _clamp(match_count / 30, 0.0, 1.0)
    recent_confidence = _clamp(recent_match_count / 10, 0.0, 1.0)
    imp_value = player_hero_stats.get("recentImp")
    if not _is_number(imp_value):
        imp_value = player_hero_stats.get("impAllTime", 0.0)
    imp_score = _clamp(float(imp_value or 0.0) / 20.0, -1.2, 1.2)
    impact = (
        (overall_diff * overall_confidence * 0.03)
        + (recent_diff * recent_confidence * 0.05)
        + (imp_score * 0.35)
    )
    return _php_round(_clamp(impact, -ROSH_PLAYER_IMPACT_CAP, ROSH_PLAYER_IMPACT_CAP), 2)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _as_int(value: Any) -> int:
    return int(value) if _is_number(value) else 0


def _optional_float(value: Any) -> float | None:
    return float(value) if _is_number(value) else None


def _round_optional(value: Any, digits: int) -> float | None:
    return _php_round(float(value), digits) if _is_number(value) else None


def _php_round(value: float, digits: int = 0) -> float:
    quantum = Decimal(1).scaleb(-digits)
    return float(Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP))


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _win_rate(win_count: int, match_count: int) -> float | None:
    if match_count <= 0:
        return None
    return _php_round((win_count / match_count) * 100, 1)
