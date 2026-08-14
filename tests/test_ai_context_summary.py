from app.ai.context_summary import AI_CONTEXT_SUMMARY_VERSION, build_ai_context_summary


def test_context_summary_compresses_mapped_signals_without_double_counting() -> None:
    view = {
        "identity": {"team_a_side": "RADIANT"},
        "market": {
            "team_a": {"fair_probability": 0.62},
            "team_b": {"fair_probability": 0.38},
            "odds_drift": {"direction": "SHORTENED"},
            "eligible": True,
            "overround": 1.04,
        },
        "draft": {
            "derived_features": {
                "current_edge": 4.0,
                "next_10m_edge": 1.5,
                "cross_over_minute": 42,
                "decomposition": {
                    "current": {
                        "hero_base": 1.0,
                        "hero_tempo": -2.5,
                        "synergy": 1.8,
                        "player": 0.4,
                    }
                },
            }
        },
        "history": {
            "team_a": {
                "base_rating": 1530.0,
                "recent_form": 0.7,
                "current_roster_strength": 1.2,
                "roster_stability": 0.9,
                "exact_roster_maps": 30,
            },
            "team_b": {
                "base_rating": 1490.0,
                "recent_form": 0.5,
                "current_roster_strength": 0.8,
                "roster_stability": 0.7,
                "exact_roster_maps": 18,
            },
            "players": [],
            "coverage": {},
        },
        "live": {
            "game_time_minutes": 24.0,
            "team_a_nw_lead": 3200,
            "trend_windows": {"5m": {"team_a_nw_delta": 900}},
            "momentum_team": "A",
        },
        "quality": {"eligible": True, "blockers": [], "warnings": []},
        "draft_live_agreement": "CONSISTENT",
    }

    summary = build_ai_context_summary(view)

    assert summary["context_summary_version"] == AI_CONTEXT_SUMMARY_VERSION
    assert summary["market_signal"]["favorite"] == "A"
    assert summary["draft_signal"]["direction_now"] == "A"
    assert summary["draft_signal"]["trajectory_10m"] == "TOWARD_B"
    assert summary["draft_signal"]["top_current_components"] == [
        {"component": "hero_tempo", "team_a_edge_pp": -2.5},
        {"component": "synergy", "team_a_edge_pp": 1.8},
        {"component": "hero_base", "team_a_edge_pp": 1.0},
    ]
    assert summary["history_signal"]["base_rating_delta_a_minus_b"] == 40.0
    assert summary["live_signal"]["leader"] == "A"
    assert summary["signal_agreement"] == {
        "market_vs_draft": "CONSISTENT",
        "market_vs_live": "CONSISTENT",
        "draft_vs_live": "CONSISTENT",
    }


def test_unresolved_side_never_turns_radiant_draft_edge_into_team_a_signal() -> None:
    view = {
        "identity": {"team_a_side": None},
        "market": {},
        "draft": {
            "derived_features": {
                "current_edge": 8.0,
                "next_10m_edge": 10.0,
                "decomposition": {"current": {"hero_base": 4.0}},
            }
        },
        "history": {},
        "live": {"team_a_nw_lead": None},
        "quality": {"eligible": True},
    }

    summary = build_ai_context_summary(view)

    assert summary["team_mapping_resolved"] is False
    assert summary["draft_signal"]["team_a_edge_now_pp"] is None
    assert summary["draft_signal"]["direction_now"] == "UNKNOWN"
    assert summary["draft_signal"]["top_current_components"] == []


def test_delayed_live_block_cannot_leak_direction_back_into_summary() -> None:
    view = {
        "identity": {"team_a_side": "DIRE"},
        "market": {"team_a": {"fair_probability": 0.55}},
        "draft": {},
        "history": {},
        "live": {
            "delayed_live_excluded": True,
            "live_data_lag_minutes": 15.0,
            "field_freshness": {"complete": True},
        },
        "quality": {"eligible": True},
    }

    summary = build_ai_context_summary(view)

    assert summary["evidence_availability"]["live"] == "EXCLUDED_DELAYED"
    assert summary["live_signal"]["team_a_nw_lead"] is None
    assert summary["live_signal"]["leader"] == "UNKNOWN"
    assert summary["signal_agreement"]["market_vs_live"] == "UNKNOWN"
