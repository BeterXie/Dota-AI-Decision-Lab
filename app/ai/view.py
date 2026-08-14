"""Deterministic AI view projection over an immutable DecisionSnapshot.

The stored snapshot keeps every raw/audit field and its hash.  This module
projects a compact, Team A/B-mapped, rounded view that is the actual AI input:

- side-relative values are mapped to canonical Team A / Team B ONLY when the
  snapshot's side identity is RESOLVED and closes over the series teams;
- derived situation metrics (market edge, economy landmarks, building counts,
  draft-live agreement) are computed here, never by the model;
- floats are rounded so the model does not see 16-digit noise;
- the output is fully deterministic (same snapshot -> same view), so replay
  and prompt-version audits stay reproducible.

Version bumps here are prompt-affecting and must be auditable: keep
AI_VIEW_VERSION aligned with PROMPT_VERSION changes.
"""

from datetime import datetime, timedelta
from typing import Any

from app.ai.dota_heroes import DOTA_HERO_NAMES
from app.ai.dota_items import DOTA_ITEM_NAMES
from app.domain.snapshot import DecisionSnapshot

AI_VIEW_VERSION = "ai-view-v1"

_MAJOR_ITEMS = {
    "Black King Bar",
    "Manta Style",
    "Linken's Sphere",
    "Aghanim's Scepter",
    "Refresher Orb",
    "Satanic",
    "Butterfly",
    "Heart of Tarrasque",
    "Abyssal Blade",
    "Monkey King Bar",
    "Daedalus",
    "Shiva's Guard",
    "Scythe of Vyse",
    "Assault Cuirass",
    "Radiance",
    "Battle Fury",
    "Eye of Skadi",
    "Mjollnir",
    "Bloodthorn",
    "Nullifier",
    "Divine Rapier",
}


def build_ai_view(
    snapshot: DecisionSnapshot,
    *,
    max_live_data_lag_seconds: float = 120.0,
) -> dict[str, Any]:
    payload = snapshot.model_dump(mode="json")
    identity = payload.get("identity") or {}
    side = _resolved_side(identity)
    team_a = _dict(identity.get("team_a"))
    team_b = _dict(identity.get("team_b"))
    team_a_id = team_a.get("id")
    team_a_side = _team_a_side(identity, side)
    live_payload = payload.get("live")
    side_identity = _dict(identity.get("side_identity"))
    anchors = _dict(_dict(payload.get("quality") or {}).get("live_anchors"))
    data_lag = anchors.get("data_lag_seconds")
    view: dict[str, Any] = {
        "ai_view_version": AI_VIEW_VERSION,
        "decision_at": payload["decision_at"],
        "mode": payload["mode"],
        "snapshot_hash": payload["snapshot_hash"],
        "identity": {
            "teams": {
                "team_a": {"id": team_a_id, "name": team_a.get("name")},
                "team_b": {"id": team_b.get("id"), "name": team_b.get("name")},
            },
            "team_a_side": team_a_side,
            "side_identity": {
                "status": side_identity.get("status"),
                "source": side_identity.get("source"),
                "confidence": side_identity.get("confidence"),
                "blocker": side_identity.get("blocker"),
            },
            "series_context": _dict(identity.get("series_context")),
        },
        "market": _market_view(payload.get("market") or {}, team_a_id, payload["decision_at"]),
        "draft": _draft_view(payload.get("draft"), side, team_a_id),
        "history": _history_view(payload.get("history") or {}),
        "live": _live_view(live_payload, side, team_a_id, team_a_side, data_lag),
        "quality": _quality_view(payload.get("quality") or {}),
    }
    draft = view["draft"]
    live = view["live"]
    if isinstance(draft, dict) and isinstance(live, dict):
        view["draft_live_agreement"] = _draft_live_agreement(draft, live, team_a_side)
    view["live"] = _exclude_delayed_live(view["live"], data_lag, max_live_data_lag_seconds)
    return _round_floats(view)


def _exclude_delayed_live(
    live_view: dict[str, Any] | None,
    lag_seconds: Any,
    max_lag_seconds: float,
) -> dict[str, Any] | None:
    """Drop delayed broadcast data from the AI input.

    DLTV broadcasts commonly lag the real-time market by ~15 minutes.  When the
    estimated lag exceeds the policy threshold, the delayed live block (state,
    trend, buildings, economy trajectory, player stats) is removed from the AI
    view so the model decides on freeze-time consistent information only: the
    real-time market, the draft, and the historical context.  The lag itself
    stays visible for transparency.
    """
    if live_view is None:
        return None
    if not isinstance(lag_seconds, (int, float)) or isinstance(lag_seconds, bool):
        return live_view
    if lag_seconds <= max_lag_seconds:
        return live_view
    return {
        "delayed_live_excluded": True,
        "exclusion_reason": (
            "DLTV broadcast data lags the real-time market beyond the allowed "
            f"{max_lag_seconds:.0f}s; delayed game state is withheld from the decision."
        ),
        "live_data_lag_minutes": round(lag_seconds / 60.0, 1),
        "field_freshness": live_view.get("field_freshness"),
    }


def _resolved_side(identity: dict[str, Any]) -> tuple[str, str] | None:
    side = identity.get("side_identity")
    if not isinstance(side, dict) or side.get("status") != "RESOLVED":
        return None
    radiant = side.get("radiant_team_id")
    dire = side.get("dire_team_id")
    team_a = _dict(identity.get("team_a")).get("id")
    team_b = _dict(identity.get("team_b")).get("id")
    if not radiant or not dire or not team_a or not team_b:
        return None
    if {radiant, dire} != {team_a, team_b}:
        return None
    return radiant, dire


def _team_a_side(identity: dict[str, Any], side: tuple[str, str] | None) -> str | None:
    if side is None:
        return None
    team_a = (identity.get("team_a") or {}).get("id")
    if side[0] == team_a:
        return "RADIANT"
    if side[1] == team_a:
        return "DIRE"
    return None


def _market_view(market: dict[str, Any], team_a_id: str | None, decision_at: str) -> dict[str, Any]:
    legs: dict[str, dict[str, Any]] = {}
    for observation in market.get("observations") or []:
        if not isinstance(observation, dict):
            continue
        key = "team_a" if observation.get("selection_team_id") == team_a_id else "team_b"
        legs[key] = {
            "price": observation.get("price"),
            "fair_probability": observation.get("fair_probability"),
            "implied_probability": observation.get("implied_probability"),
        }
    team_a_leg = legs.get("team_a") or {}
    edge_pp = None
    fair = team_a_leg.get("fair_probability")
    implied = team_a_leg.get("implied_probability")
    if isinstance(fair, (int, float)) and isinstance(implied, (int, float)):
        edge_pp = (fair - implied) * 100.0
    quality = _dict(market.get("quality"))
    return {
        "market_type": market.get("market_type"),
        "match_stage": market.get("match_stage"),
        "overround": market.get("overround"),
        "pair_skew_seconds": quality.get("pair_skew_seconds"),
        "team_a": team_a_leg or None,
        "team_b": legs.get("team_b") or None,
        "team_a_edge_pp": edge_pp,
        "eligible": quality.get("eligible"),
        "warnings": quality.get("warnings") or [],
        "odds_drift": _odds_drift_view(market.get("odds_trajectory"), decision_at),
    }


def _odds_drift_view(trajectory: Any, decision_at: str) -> dict[str, Any] | None:
    """Derive odds drift from the stored price-change path (team A implied pp)."""
    if not isinstance(trajectory, list) or len(trajectory) < 2:
        return None
    first = _dict(trajectory[0])
    last = _dict(trajectory[-1])

    def implied(price: Any) -> float | None:
        value = _float(price)
        if value is None or value <= 0:
            return None
        return 1.0 / value

    first_a = implied(first.get("price_a"))
    last_a = implied(last.get("price_a"))
    if first_a is None or last_a is None:
        return None
    try:
        decision_time = datetime.fromisoformat(decision_at.replace("Z", "+00:00"))
    except ValueError:
        decision_time = None
    five_min_ago_a = None
    if decision_time is not None:
        horizon = decision_time - timedelta(minutes=5)
        candidates = [
            implied(_dict(point).get("price_a"))
            for point in trajectory
            if _parse_time(_dict(point).get("received_at")) is not None
            and _parse_time(_dict(point).get("received_at")) <= horizon
        ]
        five_min_ago_a = candidates[-1] if candidates else None
    drift_pp = (last_a - first_a) * 100.0
    drift_5m_pp = (last_a - five_min_ago_a) * 100.0 if five_min_ago_a is not None else None
    price_first = _float(first.get("price_a"))
    price_last = _float(last.get("price_a"))
    if price_first is None or price_last is None:
        direction = None
    elif price_last < price_first - 1e-9:
        direction = "SHORTENED"
    elif price_last > price_first + 1e-9:
        direction = "LENGTHENED"
    else:
        direction = "FLAT"
    return {
        "price_a_first": price_first,
        "price_a_now": price_last,
        "implied_drift_pp_since_first": drift_pp,
        "implied_drift_pp_last_5m": drift_5m_pp,
        "direction": direction,
        "points": len(trajectory),
    }


def _float(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _draft_view(
    draft: dict[str, Any] | None,
    side: tuple[str, str] | None,
    team_a_id: str | None,
) -> dict[str, Any] | None:
    if not isinstance(draft, dict):
        return None
    features = (draft.get("curve") or {}).get("derived_features") or {}
    decomposition = features.get("decomposition") or {}
    curve_points = (draft.get("curve") or {}).get("points") or []
    mapped = side is not None
    team_a_is_radiant = mapped and side[0] == team_a_id

    def to_team(value: float | None) -> float | None:
        if value is None:
            return None
        return value if team_a_is_radiant else -value

    points = []
    for point in curve_points:
        if not isinstance(point, dict):
            continue
        minute = point.get("minute")
        if not isinstance(minute, int) or minute % 5 != 0:
            continue
        entry: dict[str, Any] = {
            "minute": minute,
            "radiant_edge": point.get("adjusted_radiant_edge"),
            "support": point.get("support"),
            "confidence": point.get("confidence"),
        }
        if mapped:
            entry["team_a_edge"] = to_team(point.get("adjusted_radiant_edge"))
        points.append(entry)

    slots = []
    for slot in draft.get("slots") or []:
        if not isinstance(slot, dict):
            continue
        entry = {
            "side": slot.get("side"),
            "position": slot.get("position"),
            "hero_id": slot.get("hero_id"),
            "hero": _hero_name(slot.get("hero_id")),
            "position_source": slot.get("source"),
            "position_confidence": slot.get("confidence"),
        }
        if mapped:
            entry["team"] = "A" if ((slot.get("side") == "radiant") == team_a_is_radiant) else "B"
        slots.append(entry)

    return {
        "complete": draft.get("complete"),
        "warnings": draft.get("warnings") or [],
        "statistics_cutoff": draft.get("statistics_cutoff"),
        "curve_model_version": (draft.get("curve") or {}).get("model_version"),
        "derived_features": {
            "current_edge": to_team(features.get("current_edge"))
            if mapped
            else features.get("current_edge"),
            "next_5m_edge": to_team(features.get("next_5m_edge"))
            if mapped
            else features.get("next_5m_edge"),
            "next_10m_edge": to_team(features.get("next_10m_edge"))
            if mapped
            else features.get("next_10m_edge"),
            "peak_edge": to_team(features.get("peak_edge"))
            if mapped
            else features.get("peak_edge"),
            "peak_minute": features.get("peak_minute"),
            "cross_over_minute": features.get("cross_over_minute"),
            "curve_slope_5m": to_team(features.get("curve_slope_5m"))
            if mapped
            else features.get("curve_slope_5m"),
            "adjustment_delta": features.get("adjustment_delta"),
            "fell_back_to_pure_score": features.get("fell_back_to_pure_score"),
            "decomposition": {
                "current": {
                    "hero_base": (decomposition.get("current") or {}).get("hero_base_adjustment"),
                    "hero_tempo": (decomposition.get("current") or {}).get("hero_tempo_adjustment"),
                    "synergy": (decomposition.get("current") or {}).get("synergy_adjustment"),
                    "player": (decomposition.get("current") or {}).get("player_adjustment"),
                    "hero": (decomposition.get("current") or {}).get("hero_adjustment"),
                },
                "peak": {
                    "hero_base": (decomposition.get("peak") or {}).get("hero_base_adjustment"),
                    "hero_tempo": (decomposition.get("peak") or {}).get("hero_tempo_adjustment"),
                    "synergy": (decomposition.get("peak") or {}).get("synergy_adjustment"),
                    "player": (decomposition.get("peak") or {}).get("player_adjustment"),
                    "hero": (decomposition.get("peak") or {}).get("hero_adjustment"),
                },
            },
        },
        "curve_points": points,
        "slots": slots,
    }


def _history_view(history: dict[str, Any]) -> dict[str, Any]:
    team_fields = (
        "last_5",
        "last_10",
        "last_20",
        "base_rating",
        "recent_form",
        "roster_stability",
        "exact_roster_maps",
        "current_roster_strength",
        "knowledge_cutoff",
    )
    players = []
    for key, team_label in (("players_a", "A"), ("players_b", "B")):
        for player in history.get(key) or []:
            if not isinstance(player, dict):
                continue
            hero_block = player.get("player_hero") or {}
            players.append(
                {
                    "team": team_label,
                    "position": player.get("position"),
                    "recent_5": player.get("recent_5"),
                    "recent_10": player.get("recent_10"),
                    "recent_20": player.get("recent_20"),
                    "sample_size": player.get("player_sample_size"),
                    "position_source": player.get("position_source"),
                    "position_confidence": player.get("position_confidence"),
                    "player_hero": {
                        "historical_maps": hero_block.get("historical_maps"),
                        "historical_win_rate": hero_block.get("historical_win_rate"),
                        "recent_180d_maps": hero_block.get("recent_180d_maps"),
                        "recent_180d_win_rate": hero_block.get("recent_180d_win_rate"),
                        "position_fit": hero_block.get("position_fit"),
                        "confidence": hero_block.get("confidence"),
                    },
                }
            )
    return {
        "team_a": {field: (history.get("team_a") or {}).get(field) for field in team_fields},
        "team_b": {field: (history.get("team_b") or {}).get(field) for field in team_fields},
        "players": players,
        "coverage": history.get("coverage") or {},
    }


def _live_view(
    live: dict[str, Any] | None,
    side: tuple[str, str] | None,
    team_a_id: str | None,
    team_a_side: str | None,
    data_lag_seconds: Any,
) -> dict[str, Any] | None:
    if not isinstance(live, dict):
        return None
    mapped = side is not None and team_a_side in {"RADIANT", "DIRE"}
    team_a_is_radiant = mapped and team_a_side == "RADIANT"

    def side_value(radiant: Any, dire: Any) -> tuple[Any, Any]:
        if radiant is None or dire is None or not mapped:
            return None, None
        return (radiant, dire) if team_a_is_radiant else (dire, radiant)

    team_a_kills, team_b_kills = side_value(live.get("radiant_kills"), live.get("dire_kills"))
    lead = live.get("radiant_nw_lead")
    team_a_nw_lead = None
    if isinstance(lead, (int, float)) and mapped:
        team_a_nw_lead = lead if team_a_is_radiant else -lead

    windows: dict[str, dict[str, Any]] = {}
    for key, window in _dict(live.get("trend")).get("windows", {}).items():
        if not isinstance(window, dict):
            continue
        nw_delta = window.get("nw_delta")
        entry: dict[str, Any] = {
            "available": window.get("available"),
            "effective_seconds": window.get("effective_seconds"),
            "nw_velocity_per_minute": window.get("nw_velocity_per_minute"),
            "radiant_nw_delta": nw_delta,
            "radiant_kills_delta": window.get("radiant_kills_delta"),
            "dire_kills_delta": window.get("dire_kills_delta"),
        }
        if mapped and isinstance(nw_delta, (int, float)):
            entry["team_a_nw_delta"] = nw_delta if team_a_is_radiant else -nw_delta
            kills_a, kills_b = side_value(
                window.get("radiant_kills_delta"), window.get("dire_kills_delta")
            )
            entry["team_a_kills_delta"] = kills_a
            entry["team_b_kills_delta"] = kills_b
        windows[key] = entry

    momentum = (live.get("trend") or {}).get("momentum_side_5m")
    momentum_team = None
    if momentum in {"RADIANT", "DIRE"} and mapped:
        momentum_team = "A" if (momentum == "RADIANT") == team_a_is_radiant else "B"

    canvas = live.get("canvas") or {}
    buildings_a, buildings_b = _building_counts(canvas, team_a_is_radiant, mapped)
    enrichment = _enrichment_view(live.get("enrichment"), team_a_is_radiant, mapped)

    freshness = live.get("field_freshness") or {}
    return {
        "game_time_minutes": _minutes(live.get("game_time_seconds")),
        "team_a_kills": team_a_kills,
        "team_b_kills": team_b_kills,
        "team_a_nw_lead": team_a_nw_lead,
        "first_blood": live.get("first_blood"),
        "trend_windows": windows,
        "momentum_team": momentum_team,
        "buildings_lost": {"team_a": buildings_a, "team_b": buildings_b},
        "economy_trajectory": _trajectory_view(live.get("charts"), team_a_is_radiant, mapped),
        "player_stats": enrichment,
        "bans": _bans_view(live.get("enrichment"), team_a_is_radiant, mapped),
        "field_freshness": {
            "complete": freshness.get("complete"),
            "effective_age_seconds": freshness.get("effective_age_seconds"),
        },
        "live_data_lag_minutes": (
            round(data_lag_seconds / 60.0, 1)
            if isinstance(data_lag_seconds, (int, float)) and not isinstance(data_lag_seconds, bool)
            else None
        ),
        "received_at": live.get("received_at"),
    }


def _trajectory_view(
    charts: dict[str, Any] | None,
    team_a_is_radiant: bool,
    mapped: bool,
) -> dict[str, Any] | None:
    if not isinstance(charts, dict):
        return None
    times = charts.get("game_times") or []
    values = charts.get("net_worth") or []
    points = []
    step = max(1, len(times) // 12) if times else 1
    for index in range(0, len(times), step):
        time = times[index]
        value = values[index] if index < len(values) else None
        if not isinstance(time, (int, float)):
            continue
        entry: dict[str, Any] = {"minute": _minutes(time), "radiant_nw_lead": value}
        if mapped and isinstance(value, (int, float)):
            entry["team_a_nw_lead"] = value if team_a_is_radiant else -value
        points.append(entry)
    team_a_values = (
        [entry.get("team_a_nw_lead") for entry in points if entry.get("team_a_nw_lead") is not None]
        if mapped
        else []
    )
    return {
        "points": points,
        "networth_at_10m": _nearest_lead(points, 10.0, mapped),
        "max_team_a_deficit": min(team_a_values) if team_a_values else None,
        "max_team_a_lead": max(team_a_values) if team_a_values else None,
    }


def _nearest_lead(
    points: list[dict[str, Any]], target_minutes: float, mapped: bool
) -> float | None:
    candidates = [
        point
        for point in points
        if (
            point.get("team_a_nw_lead") is not None
            if mapped
            else point.get("radiant_nw_lead") is not None
        )
    ]
    if not candidates:
        return None
    nearest = min(
        candidates,
        key=lambda point: abs((point.get("minute") or 0) - target_minutes),
    )
    return nearest.get("team_a_nw_lead") if mapped else nearest.get("radiant_nw_lead")


def _building_counts(
    canvas: dict[str, Any],
    team_a_is_radiant: bool,
    mapped: bool,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    radiant_tokens = canvas.get("radiant") or []
    dire_tokens = canvas.get("dire") or []

    def summarize(tokens: list) -> dict[str, Any]:
        towers = sum(
            1
            for token in tokens
            if isinstance(token, str)
            and len(token) >= 2
            and token[0] in "tmb"
            and token[1].isdigit()
        )
        barracks = sum(1 for token in tokens if isinstance(token, str) and token[-1] in {"R", "M"})
        return {"towers_lost": towers, "barracks_lost": barracks}

    radiant = summarize(radiant_tokens)
    dire = summarize(dire_tokens)
    if not mapped:
        return None, None
    return (radiant, dire) if team_a_is_radiant else (dire, radiant)


def _enrichment_view(
    enrichment: dict[str, Any] | None,
    team_a_is_radiant: bool,
    mapped: bool,
) -> dict[str, Any] | None:
    if not isinstance(enrichment, dict) or not enrichment.get("available"):
        return None
    players = []
    for entry in enrichment.get("full_stats") or []:
        if not isinstance(entry, dict):
            continue
        side = entry.get("side")
        team = None
        if mapped and side in {"radiant", "dire"}:
            team = "A" if (side == "radiant") == team_a_is_radiant else "B"
        kda = entry.get("kda") or {}
        lh = entry.get("lh") or {}
        gpm = entry.get("gpm") or {}
        item_ids = [
            item for item in (entry.get("items") or []) if isinstance(item, int) and item >= 0
        ]
        players.append(
            {
                "team": team,
                "level": entry.get("level"),
                "kda": kda,
                "net_worth": entry.get("net_worth"),
                "gold": entry.get("gold"),
                "last_hits": lh.get("first"),
                "denies": lh.get("second"),
                "gpm": gpm.get("first"),
                "xpm": gpm.get("second"),
                "items": [_item_name(item) for item in item_ids],
            }
        )
    if not players:
        return None
    result: dict[str, Any] = {
        "players": players,
        "observed_at": enrichment.get("observed_at"),
    }
    if mapped:
        for team in ("A", "B"):
            team_players = [p for p in players if p.get("team") == team]
            worths = [
                p.get("net_worth")
                for p in team_players
                if isinstance(p.get("net_worth"), (int, float))
            ]
            levels = [p.get("level") for p in team_players if isinstance(p.get("level"), int)]
            major = sorted(
                {
                    item
                    for p in team_players
                    for item in p.get("items") or []
                    if item in _MAJOR_ITEMS
                }
            )
            result[f"team_{team.lower()}"] = {
                "total_net_worth": sum(worths) if worths else None,
                "avg_level": (sum(levels) / len(levels)) if levels else None,
                "major_items": major,
            }
    return result


def _bans_view(
    enrichment: dict[str, Any] | None,
    team_a_is_radiant: bool,
    mapped: bool,
) -> dict[str, Any] | None:
    if not isinstance(enrichment, dict):
        return None
    bans = enrichment.get("bans")
    if not isinstance(bans, dict):
        return None
    radiant = [_hero_name(hero) for hero in bans.get("radiant") or [] if isinstance(hero, int)]
    dire = [_hero_name(hero) for hero in bans.get("dire") or [] if isinstance(hero, int)]
    if not mapped:
        return {"radiant": radiant, "dire": dire}
    return (
        {"team_a": radiant, "team_b": dire}
        if team_a_is_radiant
        else {"team_a": dire, "team_b": radiant}
    )


def _quality_view(quality: dict[str, Any]) -> dict[str, Any]:
    sync = quality.get("live_sync") or {}
    return {
        "eligible": quality.get("eligible"),
        "blockers": quality.get("blockers") or [],
        "warnings": quality.get("warnings") or [],
        "market_age_seconds": quality.get("market_age_seconds"),
        "live_sync": {
            "status": sync.get("status"),
            "confidence": sync.get("confidence"),
            "estimated_lag_seconds": sync.get("estimated_lag_seconds"),
            "p50_seconds": sync.get("p50_seconds"),
            "p90_seconds": sync.get("p90_seconds"),
            "jitter_seconds": sync.get("jitter_seconds"),
            "sample_size": sync.get("sample_size"),
        },
    }


def _draft_live_agreement(
    draft: dict[str, Any],
    live: dict[str, Any],
    team_a_side: str | None,
) -> str | None:
    draft_edge = (draft.get("derived_features") or {}).get("current_edge")
    live_lead = live.get("team_a_nw_lead")
    if draft_edge is None or live_lead is None:
        return None
    draft_favors_a = draft_edge > 0
    live_favors_a = live_lead > 0
    if draft_favors_a == live_favors_a:
        return "CONSISTENT"
    return "DIVERGENT"


def _minutes(seconds: Any) -> float | None:
    if isinstance(seconds, (int, float)) and not isinstance(seconds, bool):
        return round(seconds / 60.0, 1)
    return None


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _hero_name(hero_id: Any) -> str | None:
    if isinstance(hero_id, int):
        return DOTA_HERO_NAMES.get(hero_id)
    return None


def _item_name(item_id: Any) -> str | None:
    if isinstance(item_id, int):
        return DOTA_ITEM_NAMES.get(item_id, f"item-{item_id}")
    return None


def _round_floats(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 3)
    if isinstance(value, list):
        return [_round_floats(item) for item in value]
    if isinstance(value, dict):
        return {key: _round_floats(item) for key, item in value.items()}
    return value
