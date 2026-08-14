from datetime import UTC, datetime
from uuid import uuid4

from app.ai.view import build_ai_view
from app.domain.snapshot import DecisionSnapshot


def _snapshot(
    identity: dict,
    *,
    live: dict | None = None,
    market: dict | None = None,
    draft: dict | None = None,
) -> DecisionSnapshot:
    return DecisionSnapshot(
        snapshot_id=uuid4(),
        decision_at=datetime(2026, 8, 14, 3, 3, 15, tzinfo=UTC),
        created_at=datetime(2026, 8, 14, 3, 3, 15, tzinfo=UTC),
        mode="LIVE_BASIC",
        identity=identity,
        market=market or {},
        draft=draft,
        history={},
        live=live,
        quality={
            "eligible": True,
            "blockers": [],
            "warnings": [],
            "live_anchors": {
                "real_start_anchor": "2026-08-14T02:17:14Z",
                "data_lag_seconds": 900.0,
            },
        },
        snapshot_hash="fixture-hash",
    )


def _draft() -> dict:
    return {
        "complete": True,
        "warnings": [],
        "statistics_cutoff": "2026-08-14T02:17:22Z",
        "curve": {
            "model_version": "rosh-v2",
            "points": [],
            "derived_features": {
                "current_edge": 3.0,
                "next_5m_edge": 2.0,
                "next_10m_edge": 1.0,
                "peak_edge": 5.0,
                "peak_minute": 35,
                "cross_over_minute": 54,
                "curve_slope_5m": 0.4,
                "adjustment_delta": 1.2,
                "fell_back_to_pure_score": False,
                "decomposition": {
                    "current": {
                        "hero_base_adjustment": 1.0,
                        "hero_tempo_adjustment": -0.5,
                        "synergy_adjustment": 0.3,
                        "player_adjustment": 0.2,
                        "hero_adjustment": -0.1,
                    },
                    "peak": {
                        "hero_base_adjustment": -2.0,
                        "hero_tempo_adjustment": -1.5,
                        "synergy_adjustment": 0.5,
                        "player_adjustment": 0.1,
                        "hero_adjustment": 0.2,
                    },
                },
            },
        },
        "slots": [],
    }


def _resolved_identity(radiant_team_id: str) -> dict:
    team_a = "team-a"
    team_b = "team-b"
    return {
        "team_a": {"id": team_a, "name": "Team A"},
        "team_b": {"id": team_b, "name": "Team B"},
        "series_context": {"best_of": 3, "score_a": 1, "score_b": 0},
        "side_identity": {
            "status": "RESOLVED",
            "radiant_team_id": radiant_team_id,
            "dire_team_id": team_b if radiant_team_id == team_a else team_a,
            "source": "DLTV_DB_IS_RADIANT",
            "confidence": 1.0,
        },
    }


def _live() -> dict:
    return {
        "game_time_seconds": 2447,
        "radiant_kills": 28,
        "dire_kills": 32,
        "radiant_nw_lead": 5144,
        "first_blood": "dire",
        "canvas": {"radiant": ["t1"], "dire": ["t1", "t2", "mR"]},
        "charts": {
            "game_times": [0, 300, 600, 1200],
            "net_worth": [0, -500, 900, 5100],
        },
        "trend": {
            "momentum_side_5m": "RADIANT",
            "windows": {
                "5m": {
                    "available": True,
                    "effective_seconds": 300,
                    "nw_delta": 1500,
                    "nw_velocity_per_minute": 300.0,
                    "radiant_kills_delta": 3,
                    "dire_kills_delta": 1,
                }
            },
        },
        "enrichment": {
            "available": True,
            "observed_at": "2026-08-14T03:03:10Z",
            "full_stats": [
                {
                    "side": "radiant",
                    "level": 20,
                    "kda": {"kills": 5, "deaths": 2, "assists": 10},
                    "net_worth": 18000,
                    "gold": 900,
                    "items": [116, 147],
                    "lh": {"first": 210, "second": 10},
                    "gpm": {"first": 620, "second": 640},
                },
                {
                    "side": "dire",
                    "level": 18,
                    "kda": {"kills": 3, "deaths": 5, "assists": 8},
                    "net_worth": 12000,
                    "gold": 300,
                    "items": [1],
                    "lh": {"first": 150, "second": 4},
                    "gpm": {"first": 500, "second": 520},
                },
            ],
            "bans": {"radiant": [83, 121], "dire": [25, 111]},
        },
        "field_freshness": {"complete": True, "effective_age_seconds": 0.0},
    }


def test_view_maps_sides_when_team_a_is_radiant() -> None:
    view = build_ai_view(
        _snapshot(
            _resolved_identity("team-a"),
            live=_live(),
            market={
                "observations": [
                    {
                        "selection_team_id": "team-a",
                        "price": "1.86",
                        "fair_probability": 0.537,
                        "implied_probability": 0.5,
                    },
                    {
                        "selection_team_id": "team-b",
                        "price": "2.04",
                        "fair_probability": 0.463,
                        "implied_probability": 0.5,
                    },
                ],
                "odds_trajectory": [
                    {"received_at": "2026-08-14T02:20:00Z", "price_a": "2.10", "price_b": "1.80"},
                    {"received_at": "2026-08-14T03:00:00Z", "price_a": "1.80", "price_b": "2.20"},
                ],
            },
        ),
        max_live_data_lag_seconds=10_000,
    )

    assert view["identity"]["team_a_side"] == "RADIANT"
    assert view["live"]["team_a_nw_lead"] == 5144
    assert view["live"]["team_a_kills"] == 28
    assert view["live"]["momentum_team"] == "A"
    assert view["live"]["trend_windows"]["5m"]["team_a_nw_delta"] == 1500
    assert view["live"]["buildings_lost"]["team_a"] == {"towers_lost": 1, "barracks_lost": 0}
    assert view["live"]["buildings_lost"]["team_b"] == {"towers_lost": 2, "barracks_lost": 1}
    assert view["market"]["team_a_vig_adjustment_pp"] == 3.7
    assert view["market"]["odds_drift"]["direction"] == "SHORTENED"
    assert view["market"]["odds_drift"]["price_a_first"] == 2.1
    assert view["market"]["odds_drift"]["price_a_now"] == 1.8
    assert round(view["market"]["odds_drift"]["implied_drift_pp_since_first"], 2) == 7.94
    assert view["live"]["live_data_lag_minutes"] == 15.0
    assert view["live"]["player_stats"]["team_a"]["total_net_worth"] == 18000
    assert view["live"]["player_stats"]["team_a"]["major_items"] == [
        "Black King Bar",
        "Manta Style",
    ]
    assert view["live"]["bans"] == {
        "team_a": ["Treant", "Grimstroke"],
        "team_b": ["Lina", "Oracle"],
    }
    assert view["live"]["economy_trajectory"]["networth_at_10m"] == 900


def test_view_maps_sides_when_team_a_is_dire() -> None:
    view = build_ai_view(
        _snapshot(_resolved_identity("team-b"), live=_live()),
        max_live_data_lag_seconds=10_000,
    )

    assert view["identity"]["team_a_side"] == "DIRE"
    assert view["live"]["team_a_nw_lead"] == -5144
    assert view["live"]["team_a_kills"] == 32
    assert view["live"]["team_b_kills"] == 28
    assert view["live"]["momentum_team"] == "B"


def test_view_never_binds_teams_when_side_unresolved() -> None:
    identity = _resolved_identity("team-a")
    identity["side_identity"] = {
        "status": "UNRESOLVED",
        "blocker": "SIDE_IDENTITY_EVIDENCE_MISSING",
    }
    view = build_ai_view(_snapshot(identity, live=_live()), max_live_data_lag_seconds=10_000)

    assert view["identity"]["team_a_side"] is None
    assert view["live"]["team_a_nw_lead"] is None
    assert view["live"]["team_a_kills"] is None
    assert view["live"]["buildings_lost"] == {"team_a": None, "team_b": None}
    assert view["live"]["bans"] == {
        "radiant": ["Treant", "Grimstroke"],
        "dire": ["Lina", "Oracle"],
    }


def test_view_is_deterministic_and_rounded() -> None:
    snapshot = _snapshot(_resolved_identity("team-a"), live=_live())
    first = build_ai_view(snapshot, max_live_data_lag_seconds=10_000)
    second = build_ai_view(snapshot, max_live_data_lag_seconds=10_000)
    assert first == second

    def all_floats_rounded(value):
        if isinstance(value, float):
            assert abs(value - round(value, 3)) < 1e-9
        elif isinstance(value, dict):
            for item in value.values():
                all_floats_rounded(item)
        elif isinstance(value, list):
            for item in value:
                all_floats_rounded(item)

    all_floats_rounded(first)


def test_view_handles_minimal_snapshot_without_crashing() -> None:
    view = build_ai_view(
        _snapshot(
            {"team_a": {"id": "a", "name": "A"}, "team_b": {"id": "b", "name": "B"}},
            live=None,
        )
    )
    assert view["live"] is None
    assert view["draft"] is None
    assert view["market"]["team_a_vig_adjustment_pp"] is None


def test_delayed_live_data_is_excluded_from_ai_input_by_default() -> None:
    view = build_ai_view(_snapshot(_resolved_identity("team-a"), live=_live()))

    live = view["live"]
    assert live["delayed_live_excluded"] is True
    assert live["live_data_lag_minutes"] == 15.0
    assert "team_a_nw_lead" not in live
    assert "team_a_kills" not in live
    assert "player_stats" not in live
    assert "economy_trajectory" not in live
    assert "buildings_lost" not in live
    # freeze-time consistent blocks remain available
    assert view["market"] is not None
    assert view["identity"]["team_a_side"] == "RADIANT"


def test_near_real_time_live_data_is_kept() -> None:
    snapshot = _snapshot(_resolved_identity("team-a"), live=_live())
    snapshot.quality["live_anchors"]["data_lag_seconds"] = 60.0
    view = build_ai_view(snapshot)

    assert "delayed_live_excluded" not in view["live"]
    assert view["live"]["team_a_nw_lead"] == 5144
    assert view["live"]["live_data_lag_minutes"] == 1.0


def test_delayed_live_exclusion_also_drops_draft_live_agreement() -> None:
    view = build_ai_view(_snapshot(_resolved_identity("team-a"), live=_live(), draft=_draft()))

    assert view["live"]["delayed_live_excluded"] is True
    assert "draft_live_agreement" not in view


def test_decomposition_maps_to_team_a_when_team_a_is_dire() -> None:
    view = build_ai_view(
        _snapshot(_resolved_identity("team-b"), live=_live(), draft=_draft()),
        max_live_data_lag_seconds=10_000,
    )

    current = view["draft"]["derived_features"]["decomposition"]["current"]
    assert current["hero_base"] == -1.0
    assert current["synergy"] == -0.3
    assert current["hero_tempo"] == 0.5
    assert view["draft"]["derived_features"]["adjustment_delta"] == -1.2
    assert view["draft"]["derived_features"]["current_edge"] == -3.0
