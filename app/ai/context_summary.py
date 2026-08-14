"""Deterministic semantic compression for the provider-facing AI input.

This module does not create new evidence and does not make a betting decision.
It only converts already-derived ai-view fields into compact directional and
comparative signals that are easier for an LLM to consume consistently.
"""

from typing import Any

AI_CONTEXT_SUMMARY_VERSION = "ai-context-summary-v1"


def build_ai_context_summary(view: dict[str, Any]) -> dict[str, Any]:
    identity = _dict(view.get("identity"))
    market = _dict(view.get("market"))
    draft = _dict(view.get("draft"))
    history = _dict(view.get("history"))
    quality = _dict(view.get("quality"))
    live_value = view.get("live")
    live = _dict(live_value)

    team_mapping_resolved = identity.get("team_a_side") in {"RADIANT", "DIRE"}
    delayed_live = live.get("delayed_live_excluded") is True
    live_availability = (
        "MISSING"
        if not isinstance(live_value, dict)
        else "EXCLUDED_DELAYED"
        if delayed_live
        else "AVAILABLE"
    )

    team_a_market = _dict(market.get("team_a"))
    team_b_market = _dict(market.get("team_b"))
    probability_a = _number(team_a_market.get("fair_probability"))
    probability_b = _number(team_b_market.get("fair_probability"))
    market_direction = _probability_direction(probability_a)

    draft_features = _dict(draft.get("derived_features"))
    draft_edge_now = _number(draft_features.get("current_edge")) if team_mapping_resolved else None
    draft_edge_10m = _number(draft_features.get("next_10m_edge")) if team_mapping_resolved else None
    draft_direction = _signed_direction(draft_edge_now)
    draft_trajectory = _trajectory_direction(draft_edge_now, draft_edge_10m)
    top_draft_components = _top_draft_components(draft_features, team_mapping_resolved)

    history_a = _dict(history.get("team_a"))
    history_b = _dict(history.get("team_b"))
    rating_delta = _difference(history_a.get("base_rating"), history_b.get("base_rating"))
    form_delta = _difference(history_a.get("recent_form"), history_b.get("recent_form"))
    roster_strength_delta = _difference(
        history_a.get("current_roster_strength"), history_b.get("current_roster_strength")
    )
    roster_stability_delta = _difference(
        history_a.get("roster_stability"), history_b.get("roster_stability")
    )

    live_lead = None if delayed_live else _number(live.get("team_a_nw_lead"))
    live_direction = _signed_direction(live_lead)
    live_5m = _dict(_dict(live.get("trend_windows")).get("5m"))
    live_5m_delta = None if delayed_live else _number(live_5m.get("team_a_nw_delta"))

    return {
        "context_summary_version": AI_CONTEXT_SUMMARY_VERSION,
        "team_mapping_resolved": team_mapping_resolved,
        "evidence_availability": {
            "market": bool(team_a_market or team_b_market),
            "draft": bool(draft),
            "history": _history_available(history),
            "live": live_availability,
            "quality_eligible": quality.get("eligible"),
        },
        "market_signal": {
            "team_a_fair_probability": probability_a,
            "team_b_fair_probability": probability_b,
            "favorite": market_direction,
            "team_a_odds_drift": _dict(market.get("odds_drift")).get("direction"),
            "eligible": market.get("eligible"),
            "overround": market.get("overround"),
        },
        "draft_signal": {
            "team_a_edge_now_pp": draft_edge_now,
            "team_a_edge_next_10m_pp": draft_edge_10m,
            "direction_now": draft_direction,
            "trajectory_10m": draft_trajectory,
            "cross_over_minute": (
                draft_features.get("cross_over_minute") if team_mapping_resolved else None
            ),
            "top_current_components": top_draft_components,
        },
        "history_signal": {
            "base_rating_delta_a_minus_b": rating_delta,
            "recent_form_delta_a_minus_b": form_delta,
            "roster_strength_delta_a_minus_b": roster_strength_delta,
            "roster_stability_delta_a_minus_b": roster_stability_delta,
            "exact_roster_maps_a": history_a.get("exact_roster_maps"),
            "exact_roster_maps_b": history_b.get("exact_roster_maps"),
        },
        "live_signal": {
            "availability": live_availability,
            "game_time_minutes": None if delayed_live else live.get("game_time_minutes"),
            "team_a_nw_lead": live_lead,
            "leader": live_direction,
            "team_a_nw_delta_5m": live_5m_delta,
            "momentum_team": None if delayed_live else live.get("momentum_team"),
            "draft_live_agreement": view.get("draft_live_agreement"),
        },
        "signal_agreement": {
            "market_vs_draft": _agreement(market_direction, draft_direction),
            "market_vs_live": _agreement(market_direction, live_direction),
            "draft_vs_live": _agreement(draft_direction, live_direction),
        },
        "data_quality": {
            "eligible": quality.get("eligible"),
            "blockers": quality.get("blockers") or [],
            "warnings": quality.get("warnings") or [],
            "live_sync": quality.get("live_sync"),
        },
    }


def _top_draft_components(
    draft_features: dict[str, Any], team_mapping_resolved: bool
) -> list[dict[str, Any]]:
    if not team_mapping_resolved:
        return []
    current = _dict(_dict(draft_features.get("decomposition")).get("current"))
    components = [
        {"component": name, "team_a_edge_pp": value}
        for name, raw_value in current.items()
        if (value := _number(raw_value)) is not None
    ]
    components.sort(key=lambda item: (-abs(item["team_a_edge_pp"]), item["component"]))
    return components[:3]


def _history_available(history: dict[str, Any]) -> bool:
    if history.get("players"):
        return True
    for key in ("team_a", "team_b", "coverage"):
        value = history.get(key)
        if isinstance(value, dict) and any(item is not None for item in value.values()):
            return True
    return False


def _probability_direction(probability_a: float | None) -> str:
    if probability_a is None:
        return "UNKNOWN"
    if probability_a > 0.5:
        return "A"
    if probability_a < 0.5:
        return "B"
    return "EVEN"


def _signed_direction(value: float | None) -> str:
    if value is None:
        return "UNKNOWN"
    if value > 0:
        return "A"
    if value < 0:
        return "B"
    return "EVEN"


def _trajectory_direction(current: float | None, future: float | None) -> str:
    if current is None or future is None:
        return "UNKNOWN"
    delta = future - current
    if delta > 0:
        return "TOWARD_A"
    if delta < 0:
        return "TOWARD_B"
    return "STABLE"


def _agreement(left: str, right: str) -> str:
    if left not in {"A", "B"} or right not in {"A", "B"}:
        return "UNKNOWN"
    return "CONSISTENT" if left == right else "DIVERGENT"


def _difference(left: Any, right: Any) -> float | None:
    left_number = _number(left)
    right_number = _number(right)
    if left_number is None or right_number is None:
        return None
    return round(left_number - right_number, 3)


def _number(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
