from collections.abc import Mapping, Sequence
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from app.providers.stratz.draft_queries import (
    QUERY_VERSION,
    REFERENCE_COMMIT,
    REFERENCE_REPOSITORY,
    ROSH_BRACKET,
    ROSH_BRACKET_BASIC,
    calculate_player_impact,
    normalize_player_hero_highlight,
)

ROSH_MIN_TIME = 20
ROSH_MAX_TIME = 60
ROSH_GRAPH_WINDOW_RADIUS = 1
ROSH_HERO_BASE_PRIOR_MATCH_COUNT = 500
ROSH_HERO_TEMPO_PRIOR_MATCH_COUNT = 500
ROSH_HERO_TEMPO_WEIGHT = 0.35
ROSH_HERO_ADJUSTMENT_WEIGHT = 2.0
ROSH_SYNERGY_RELIABILITY_MATCH_COUNT = 100
ROSH_SYNERGY_ADJUSTMENT_CAP = 30.0
ROSH_TEAM_PLAYER_ADJUSTMENT_CAP = 2.5
MODEL_VERSION = "rosh-c7a54b5-v1"


def score_rosh_lineups(
    radiant_heroes: Sequence[int],
    dire_heroes: Sequence[int],
    analysis: Mapping[str, Mapping[str, Any]],
    *,
    radiant_player_highlights: Sequence[Mapping[str, Any] | None] | None = None,
    dire_player_highlights: Sequence[Mapping[str, Any] | None] | None = None,
    player_slot_statuses: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    if len(radiant_heroes) != 5 or len(dire_heroes) != 5:
        raise ValueError("R.O.S.H. scoring requires five position-ordered heroes per side")
    if (radiant_player_highlights is None) != (dire_player_highlights is None):
        raise ValueError("player highlights must be provided for both sides or neither")
    if radiant_player_highlights is not None and (
        len(radiant_player_highlights) != 5 or len(dire_player_highlights or ()) != 5
    ):
        raise ValueError("player highlights must contain five slots per side")
    radiant_picks = [
        {"heroId": int(hero_id), "positionId": index}
        for index, hero_id in enumerate(radiant_heroes, start=1)
    ]
    dire_picks = [
        {"heroId": int(hero_id), "positionId": index}
        for index, hero_id in enumerate(dire_heroes, start=1)
    ]
    result = score_rosh_picks(
        radiant_picks,
        dire_picks,
        analysis,
        radiant_player_highlights=radiant_player_highlights,
        dire_player_highlights=dire_player_highlights,
        player_slot_statuses=player_slot_statuses,
    )
    result["model_version"] = MODEL_VERSION
    result["query_version"] = QUERY_VERSION
    result["reference"] = {
        "repository": REFERENCE_REPOSITORY,
        "commit": REFERENCE_COMMIT,
    }
    return result


def score_rosh_picks(
    radiant_picks: Sequence[Mapping[str, Any]],
    dire_picks: Sequence[Mapping[str, Any]],
    analysis: Mapping[str, Mapping[str, Any]],
    *,
    radiant_player_highlights: Sequence[Mapping[str, Any] | None] | None = None,
    dire_player_highlights: Sequence[Mapping[str, Any] | None] | None = None,
    player_slot_statuses: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    normalized_radiant = _normalize_picks(radiant_picks)
    normalized_dire = _normalize_picks(dire_picks)
    if (radiant_player_highlights is None) != (dire_player_highlights is None):
        raise ValueError("player highlights must be provided for both sides or neither")
    if radiant_player_highlights is not None and (
        len(radiant_player_highlights) != len(normalized_radiant)
        or len(dire_player_highlights or ()) != len(normalized_dire)
    ):
        raise ValueError("player highlights must align with explicit picks")
    player_analysis = _build_player_analysis(
        radiant_player_highlights,
        dire_player_highlights,
        player_slot_statuses,
    )
    pure_table = _build_minute_table(
        normalized_radiant, normalized_dire, analysis, player_adjustment=0.0
    )
    adjusted_table = _build_minute_table(
        normalized_radiant,
        normalized_dire,
        analysis,
        player_adjustment=player_analysis["netAdjustment"],
    )
    pure_score = pure_table[-1]["win_rate_graph"] if pure_table else None
    adjusted_score = adjusted_table[-1]["win_rate_graph"] if adjusted_table else None
    return {
        "bracket": ROSH_BRACKET,
        "bracket_basic": ROSH_BRACKET_BASIC,
        "pure_lineup_score": pure_score,
        "player_adjusted_lineup_score": adjusted_score,
        "pure_minute_table": pure_table,
        "minute_table": adjusted_table,
        "player_analysis": player_analysis,
        "used_player_adjustment": bool(
            player_analysis["enabled"] and player_analysis["resolvedCount"] > 0
        ),
        "fell_back_to_pure_score": bool(
            player_analysis["enabled"] and player_analysis["resolvedCount"] == 0
        ),
    }


def _normalize_picks(picks: Sequence[Mapping[str, Any]]) -> list[dict[str, int]]:
    normalized: list[dict[str, int]] = []
    for pick in picks:
        hero_id = pick.get("heroId")
        position_id = pick.get("positionId")
        if not _is_int(hero_id) or not _is_int(position_id):
            continue
        if hero_id <= 0 or not 1 <= position_id <= 5:
            continue
        normalized.append({"heroId": hero_id, "positionId": position_id})
    return normalized


def _build_player_analysis(
    radiant_highlights: Sequence[Mapping[str, Any] | None] | None,
    dire_highlights: Sequence[Mapping[str, Any] | None] | None,
    slot_statuses: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    if radiant_highlights is None or dire_highlights is None:
        return {
            "enabled": False,
            "source": "plus.playerHeroHighlight",
            "selectedCount": 0,
            "resolvedCount": 0,
            "fallbackCount": 0,
            "radiantTotalImpact": 0.0,
            "direTotalImpact": 0.0,
            "netAdjustment": 0.0,
        }
    normalized_radiant = [_ensure_normalized(item) for item in radiant_highlights]
    normalized_dire = [_ensure_normalized(item) for item in dire_highlights]
    radiant_total = sum(calculate_player_impact(item) for item in normalized_radiant)
    dire_total = sum(calculate_player_impact(item) for item in normalized_dire)
    all_highlights = [*normalized_radiant, *normalized_dire]
    resolved_count = sum(item is not None for item in all_highlights)
    if slot_statuses is not None and len(slot_statuses) != 10:
        raise ValueError("player slot statuses must contain ten slots")
    selected_count = (
        sum(status.get("selected") is True for status in slot_statuses)
        if slot_statuses is not None
        else resolved_count
    )
    fallback_count = (
        sum(
            isinstance(status.get("fallback_reason"), str)
            and bool(str(status.get("fallback_reason")).strip())
            for status in slot_statuses
            if status.get("selected") is True
        )
        if slot_statuses is not None
        else 10 - resolved_count
    )
    net_adjustment = _php_round(
        _clamp(
            (radiant_total - dire_total) / 5,
            -ROSH_TEAM_PLAYER_ADJUSTMENT_CAP,
            ROSH_TEAM_PLAYER_ADJUSTMENT_CAP,
        ),
        1,
    )
    return {
        "enabled": True,
        "source": "plus.playerHeroHighlight",
        "selectedCount": selected_count,
        "resolvedCount": resolved_count,
        "fallbackCount": fallback_count,
        "radiantTotalImpact": _php_round(radiant_total, 2),
        "direTotalImpact": _php_round(dire_total, 2),
        "netAdjustment": net_adjustment,
    }


def _ensure_normalized(highlight: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if highlight is None:
        return None
    if "recentWindow" in highlight and "recentMatchCount" in highlight:
        return dict(highlight)
    return normalize_player_hero_highlight(highlight)


def _build_minute_table(
    radiant_picks: Sequence[Mapping[str, int]],
    dire_picks: Sequence[Mapping[str, int]],
    analysis: Mapping[str, Mapping[str, Any]],
    *,
    player_adjustment: float,
) -> list[dict[str, Any]]:
    position_data = _build_hero_position_data(analysis.get("heroes_meta_positions", {}))
    hero_base_adjustment = (
        _team_average_difference(
            _sum_position_effects(radiant_picks, position_data),
            len(radiant_picks),
            _sum_position_effects(dire_picks, position_data),
            len(dire_picks),
        )
        * ROSH_HERO_ADJUSTMENT_WEIGHT
    )
    graph = _build_computed_graph_data(
        analysis.get("hero_stats_by_time_bracket", {}), position_data
    )
    if not graph:
        return []
    synergy_data = _build_synergy_data(analysis.get("synergy", {}))
    synergy_offset = _calculate_synergy_offset(radiant_picks, dire_picks, synergy_data)
    minute_table: list[dict[str, Any]] = []
    for minute in sorted(graph):
        bucket = graph[minute]
        radiant_tempo_total = 0.0
        dire_tempo_total = 0.0
        minute_match_count = 0
        total_match_count = 0
        for pick in radiant_picks:
            stats = bucket["heroes"].get(pick["positionId"], {}).get(pick["heroId"])
            if stats is not None:
                radiant_tempo_total += stats["tempo_effect"]
                minute_match_count += stats["match_count"]
                total_match_count += stats["total_match_count"]
        for pick in dire_picks:
            stats = bucket["heroes"].get(pick["positionId"], {}).get(pick["heroId"])
            if stats is not None:
                dire_tempo_total += stats["tempo_effect"]
                minute_match_count += stats["match_count"]
                total_match_count += stats["total_match_count"]
        hero_tempo_adjustment = (
            _team_average_difference(
                radiant_tempo_total,
                len(radiant_picks),
                dire_tempo_total,
                len(dire_picks),
            )
            * ROSH_HERO_ADJUSTMENT_WEIGHT
        )
        hero_adjustment = hero_base_adjustment + hero_tempo_adjustment
        edge = _php_round(hero_adjustment + synergy_offset + player_adjustment, 1)
        match_percentage = (
            _php_round((minute_match_count / total_match_count) * 100, 1)
            if total_match_count > 0
            else 0.0
        )
        minute_table.append(
            {
                "minute": bucket["time"],
                "time_start": bucket["time_start"],
                "time_end": bucket["time_end"],
                "advantage_side": ("radiant" if edge > 0 else "dire" if edge < 0 else "even"),
                "advantage_percent": _php_round(abs(edge), 1),
                "radiant_advantage": _php_round(edge, 1) if edge > 0 else 0.0,
                "dire_advantage": _php_round(abs(edge), 1) if edge < 0 else 0.0,
                "match_percentage": match_percentage,
                "support": minute_match_count,
                "win_rate_graph": edge,
                "hero_adjustment": _php_round(hero_adjustment, 1),
                "hero_base_adjustment": _php_round(hero_base_adjustment, 1),
                "hero_tempo_adjustment": _php_round(hero_tempo_adjustment, 1),
                "synergy_adjustment": _php_round(synergy_offset, 1),
                "player_adjustment": _php_round(player_adjustment, 1),
            }
        )
    return minute_table


def _build_hero_position_data(
    heroes_meta_positions: Mapping[str, Any],
) -> dict[int, dict[int, dict[str, float | int]]]:
    result: dict[int, dict[int, dict[str, float | int]]] = {}
    for position_id in range(1, 6):
        rows = heroes_meta_positions.get(f"heroesPos_{position_id}", [])
        for row in rows if isinstance(rows, list) else []:
            hero_id = row.get("heroId")
            match_count = row.get("matchCount")
            win_count = row.get("winCount")
            if (
                not _is_int(hero_id)
                or not _is_number(match_count)
                or not _is_number(win_count)
                or int(match_count) <= 0
            ):
                continue
            matches = int(match_count)
            raw_win_rate_diff = ((int(win_count) / matches) * 100) - 50
            confidence = matches / (matches + ROSH_HERO_BASE_PRIOR_MATCH_COUNT)
            result.setdefault(position_id, {})[hero_id] = {
                "match_count": matches,
                "raw_win_rate_diff": raw_win_rate_diff,
                "base_effect": raw_win_rate_diff * confidence,
            }
    return result


def _sum_position_effects(
    picks: Sequence[Mapping[str, int]],
    position_data: Mapping[int, Mapping[int, Mapping[str, float | int]]],
) -> float:
    return sum(
        float(
            position_data.get(pick["positionId"], {})
            .get(pick["heroId"], {})
            .get("base_effect", 0.0)
        )
        for pick in picks
    )


def _team_average_difference(
    radiant_total: float, radiant_count: int, dire_total: float, dire_count: int
) -> float:
    radiant_average = radiant_total / radiant_count if radiant_count > 0 else 0.0
    dire_average = dire_total / dire_count if dire_count > 0 else 0.0
    return radiant_average - dire_average


def _build_computed_graph_data(
    hero_stats_by_time: Mapping[str, Any],
    position_data: Mapping[int, Mapping[int, Mapping[str, float | int]]],
) -> dict[int, dict[str, Any]]:
    graph: dict[int, dict[str, Any]] = {}
    for position_id in range(1, 6):
        raw_rows = hero_stats_by_time.get(f"heroStatsByTime_{position_id}", [])
        rows = [
            row
            for row in raw_rows
            if isinstance(raw_rows, list)
            and isinstance(row, Mapping)
            and _is_int(row.get("heroId"))
            and _is_number(row.get("time"))
            and _is_number(row.get("winCount"))
            and _is_number(row.get("matchCount"))
        ]
        rows.sort(key=lambda row: (row["heroId"], row["time"]))
        normalized_rows: list[dict[str, int]] = []
        total_match_count_by_hero: dict[int, int] = {}
        for index, row in enumerate(rows):
            hero_id = int(row["heroId"])
            match_count = int(row["matchCount"])
            win_count = int(row["winCount"])
            next_row = rows[index + 1] if index + 1 < len(rows) else None
            same_hero_next = next_row is not None and int(next_row.get("heroId", -1)) == hero_id
            minute_matches = (
                max(0, match_count - int(next_row.get("matchCount", 0)))
                if same_hero_next
                else match_count
            )
            minute_wins = (
                max(0, win_count - int(next_row.get("winCount", 0)))
                if same_hero_next
                else win_count
            )
            total_match_count_by_hero[hero_id] = (
                total_match_count_by_hero.get(hero_id, 0) + minute_matches
            )
            normalized_rows.append(
                {
                    "heroId": hero_id,
                    "time": int(row["time"]),
                    "matchCount": minute_matches,
                    "winCount": minute_wins,
                }
            )
        for index, row in enumerate(normalized_rows):
            hero_id = row["heroId"]
            minute = row["time"]
            if minute < ROSH_MIN_TIME or minute > ROSH_MAX_TIME:
                continue
            base_diff = position_data.get(position_id, {}).get(hero_id, {}).get("raw_win_rate_diff")
            if not _is_number(base_diff):
                continue
            bucket = graph.setdefault(
                minute,
                {
                    "time": minute,
                    "time_start": max(ROSH_MIN_TIME, minute - ROSH_GRAPH_WINDOW_RADIUS),
                    "time_end": min(ROSH_MAX_TIME, minute + ROSH_GRAPH_WINDOW_RADIUS),
                    "heroes": {},
                },
            )
            start = max(0, index - ROSH_GRAPH_WINDOW_RADIUS)
            end = min(len(normalized_rows), index + ROSH_GRAPH_WINDOW_RADIUS + 1)
            window_rows = [
                candidate
                for candidate in normalized_rows[start:end]
                if candidate["heroId"] == hero_id
            ]
            window_matches = sum(candidate["matchCount"] for candidate in window_rows)
            window_wins = sum(candidate["winCount"] for candidate in window_rows)
            if window_matches <= 0:
                continue
            duration_diff = ((window_wins / window_matches) * 100) - 50
            confidence = window_matches / (window_matches + ROSH_HERO_TEMPO_PRIOR_MATCH_COUNT)
            bucket["heroes"].setdefault(position_id, {})[hero_id] = {
                "hero_id": hero_id,
                "tempo_effect": (
                    (duration_diff - float(base_diff)) * confidence * ROSH_HERO_TEMPO_WEIGHT
                ),
                "match_count": row["matchCount"],
                "total_match_count": total_match_count_by_hero[hero_id],
            }
    return graph


def _build_synergy_data(
    raw_synergy: Mapping[str, Any],
) -> dict[str, dict[int, dict[int, dict[str, float | int]]]]:
    with_data: dict[int, dict[int, dict[str, float | int]]] = {}
    vs_data: dict[int, dict[int, dict[str, float | int]]] = {}
    for week_index in range(1, 5):
        rows = raw_synergy.get(f"matchUp_Prev_Week_{week_index}", [])
        for row in rows if isinstance(rows, list) else []:
            hero_id = row.get("heroId") if isinstance(row, Mapping) else None
            if not _is_int(hero_id):
                continue
            for key, target in (("with", with_data), ("vs", vs_data)):
                entries = row.get(key, [])
                for entry in entries if isinstance(entries, list) else []:
                    hero_id_2 = entry.get("heroId2") if isinstance(entry, Mapping) else None
                    match_count = entry.get("matchCount") if isinstance(entry, Mapping) else None
                    synergy = entry.get("synergy") if isinstance(entry, Mapping) else None
                    if (
                        not _is_int(hero_id_2)
                        or not _is_number(match_count)
                        or not _is_number(synergy)
                    ):
                        continue
                    _merge_synergy_entry(
                        target, hero_id, hero_id_2, int(match_count), float(synergy)
                    )
    return {
        "with": _apply_synergy_reliability(with_data),
        "vs": _apply_synergy_reliability(vs_data),
    }


def _merge_synergy_entry(
    lookup: dict[int, dict[int, dict[str, float | int]]],
    hero_id: int,
    hero_id_2: int,
    match_count: int,
    synergy: float,
) -> None:
    entry = lookup.setdefault(hero_id, {}).setdefault(hero_id_2, {"matchCount": 0, "synergy": 0.0})
    current_count = int(entry["matchCount"])
    total_count = current_count + match_count
    if total_count <= 0:
        return
    weighted = float(entry["synergy"]) * (current_count / total_count) + synergy * (
        match_count / total_count
    )
    lookup[hero_id][hero_id_2] = {"matchCount": total_count, "synergy": weighted}


def _apply_synergy_reliability(
    lookup: dict[int, dict[int, dict[str, float | int]]],
) -> dict[int, dict[int, dict[str, float | int]]]:
    for entries in lookup.values():
        for entry in entries.values():
            confidence = _clamp(
                int(entry["matchCount"]) / ROSH_SYNERGY_RELIABILITY_MATCH_COUNT,
                0.0,
                1.0,
            )
            entry["synergy"] = _php_round(float(entry["synergy"]) * confidence, 2)
    return lookup


def _calculate_synergy_offset(
    radiant_picks: Sequence[Mapping[str, int]],
    dire_picks: Sequence[Mapping[str, int]],
    synergy_data: Mapping[str, Mapping[int, Mapping[int, Mapping[str, float | int]]]],
) -> float:
    with_lookup = synergy_data.get("with", {})
    vs_lookup = synergy_data.get("vs", {})
    radiant_synergy = _sum_team_pair_synergies(radiant_picks, with_lookup)
    dire_synergy = _sum_team_pair_synergies(dire_picks, with_lookup)
    matchup = _sum_matchup_advantages(radiant_picks, dire_picks, vs_lookup)
    return _clamp(
        radiant_synergy - dire_synergy + matchup,
        -ROSH_SYNERGY_ADJUSTMENT_CAP,
        ROSH_SYNERGY_ADJUSTMENT_CAP,
    )


def _sum_team_pair_synergies(
    picks: Sequence[Mapping[str, int]],
    lookup: Mapping[int, Mapping[int, Mapping[str, float | int]]],
) -> float:
    total = 0.0
    for left_index in range(len(picks)):
        for right_index in range(left_index + 1, len(picks)):
            total += _average_pair_synergy(
                picks[left_index]["heroId"], picks[right_index]["heroId"], lookup
            )
    return total


def _sum_matchup_advantages(
    radiant_picks: Sequence[Mapping[str, int]],
    dire_picks: Sequence[Mapping[str, int]],
    lookup: Mapping[int, Mapping[int, Mapping[str, float | int]]],
) -> float:
    advantage = 0.0
    for radiant_pick in radiant_picks:
        for dire_pick in dire_picks:
            radiant = _lookup_synergy(lookup, radiant_pick["heroId"], dire_pick["heroId"])
            dire = _lookup_synergy(lookup, dire_pick["heroId"], radiant_pick["heroId"])
            if radiant is not None and dire is not None:
                advantage += (radiant - dire) / 2
            elif radiant is not None:
                advantage += radiant
            elif dire is not None:
                advantage -= dire
    return advantage


def _average_pair_synergy(
    hero_id: int,
    hero_id_2: int,
    lookup: Mapping[int, Mapping[int, Mapping[str, float | int]]],
) -> float:
    left = _lookup_synergy(lookup, hero_id, hero_id_2)
    right = _lookup_synergy(lookup, hero_id_2, hero_id)
    if left is not None and right is not None:
        return (left + right) / 2
    if left is not None:
        return left
    return right if right is not None else 0.0


def _lookup_synergy(
    lookup: Mapping[int, Mapping[int, Mapping[str, float | int]]],
    hero_id: int,
    hero_id_2: int,
) -> float | None:
    value = lookup.get(hero_id, {}).get(hero_id_2, {}).get("synergy")
    return float(value) if _is_number(value) else None


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _php_round(value: float, digits: int = 0) -> float:
    quantum = Decimal(1).scaleb(-digits)
    return float(Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP))
