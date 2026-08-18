from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.ai.context_profiles import (
    MARKET_ONLY_CONTEXT_VERSION,
    NO_DRAFT_CONTEXT_VERSION,
    NO_LIVE_CONTEXT_VERSION,
    NO_PLAYER_FORM_CONTEXT_VERSION,
    NO_PLAYER_HERO_CONTEXT_VERSION,
    NO_ROSTER_CONTEXT_VERSION,
    SCHEMA_ALIGNED_CONTEXT_VERSION,
    build_context_profile_view,
    context_profile_metadata,
)
from app.ai.input import AI_VIEW_VERSION, build_ai_input
from app.domain.snapshot import DecisionMode, DecisionSnapshot

NOW = datetime(2026, 8, 18, 9, 30, tzinfo=UTC)
TEAM_A = str(uuid4())
TEAM_B = str(uuid4())


def test_production_ai_input_path_stays_exactly_on_ai_view_v6() -> None:
    snapshot = _snapshot()

    assert build_ai_input(snapshot) == build_ai_input(
        snapshot,
        ai_view_version=AI_VIEW_VERSION,
    )
    assert "ai_view_version" not in build_ai_input(snapshot)


def test_schema_aligned_context_recovers_player_evidence_already_stored_in_snapshot() -> None:
    snapshot = _snapshot()
    production = build_context_profile_view(snapshot)
    aligned = build_context_profile_view(
        snapshot,
        ai_view_version=SCHEMA_ALIGNED_CONTEXT_VERSION,
    )

    # This captures the discovered v6 projection mismatch without mutating v6.
    production_player = production["history"]["players"][0]
    assert production_player["recent_10"] is None
    assert production_player["player_hero"]["historical_maps"] is None

    player = aligned["history"]["players"][0]
    assert player["team"] == "A"
    assert player["base_strength"] == 0.64
    assert player["recent_form"] == 0.71
    assert player["recent_form_confidence"] == 0.8
    assert player["current_hero"] == 1
    assert player["player_hero"] == {
        "adjusted_strength": 0.76,
        "sample_size": 42,
        "position_fit": 0.91,
        "confidence": 0.85,
    }
    assert aligned["history"]["team_a"] == production["history"]["team_a"]
    assert aligned["market"] == production["market"]
    assert aligned["draft"] == production["draft"]
    assert aligned["live"] == production["live"]


def test_ablation_profiles_remove_only_the_intended_context_group() -> None:
    snapshot = _snapshot()
    aligned = build_context_profile_view(
        snapshot,
        ai_view_version=SCHEMA_ALIGNED_CONTEXT_VERSION,
    )

    no_roster = build_context_profile_view(snapshot, ai_view_version=NO_ROSTER_CONTEXT_VERSION)
    assert "current_roster_strength" not in no_roster["history"]["team_a"]
    assert "roster_stability" not in no_roster["history"]["team_a"]
    assert no_roster["history"]["players"] == aligned["history"]["players"]
    assert no_roster["draft"] == aligned["draft"]

    no_player_form = build_context_profile_view(
        snapshot,
        ai_view_version=NO_PLAYER_FORM_CONTEXT_VERSION,
    )
    form_player = no_player_form["history"]["players"][0]
    assert "base_strength" not in form_player
    assert "recent_form" not in form_player
    assert "recent_form_confidence" not in form_player
    assert form_player["player_hero"] == aligned["history"]["players"][0]["player_hero"]
    assert no_player_form["history"]["team_a"] == aligned["history"]["team_a"]

    no_player_hero = build_context_profile_view(
        snapshot,
        ai_view_version=NO_PLAYER_HERO_CONTEXT_VERSION,
    )
    hero_player = no_player_hero["history"]["players"][0]
    assert "player_hero" not in hero_player
    assert hero_player["base_strength"] == 0.64
    assert no_player_hero["history"]["team_a"] == aligned["history"]["team_a"]

    no_draft = build_context_profile_view(snapshot, ai_view_version=NO_DRAFT_CONTEXT_VERSION)
    assert "draft" not in no_draft
    assert "draft_live_agreement" not in no_draft
    assert no_draft["history"] == aligned["history"]
    assert no_draft["live"] == aligned["live"]

    no_live = build_context_profile_view(snapshot, ai_view_version=NO_LIVE_CONTEXT_VERSION)
    assert "live" not in no_live
    assert "draft_live_agreement" not in no_live
    assert no_live["history"] == aligned["history"]
    assert no_live["draft"] == aligned["draft"]

    market_only = build_context_profile_view(snapshot, ai_view_version=MARKET_ONLY_CONTEXT_VERSION)
    assert "history" not in market_only
    assert "draft" not in market_only
    assert "live" not in market_only
    assert market_only["market"] == aligned["market"]
    assert market_only["identity"] == aligned["identity"]
    assert market_only["quality"] == aligned["quality"]


def test_profile_metadata_exposes_reference_and_removed_evidence() -> None:
    assert context_profile_metadata(AI_VIEW_VERSION) is None
    metadata = context_profile_metadata(NO_PLAYER_FORM_CONTEXT_VERSION)
    assert metadata is not None
    assert metadata["reference_ai_view_version"] == SCHEMA_ALIGNED_CONTEXT_VERSION
    assert metadata["removed_evidence"] == ["player_form"]


def test_unknown_context_profile_is_rejected_fail_closed() -> None:
    with pytest.raises(ValueError, match="unknown AI context profile"):
        build_ai_input(_snapshot(), ai_view_version="ctx-made-up-v99")


def _snapshot() -> DecisionSnapshot:
    return DecisionSnapshot(
        snapshot_id=uuid4(),
        decision_at=NOW,
        created_at=NOW,
        mode=DecisionMode.LIVE_FULL,
        identity={
            "team_a": {"id": TEAM_A, "name": "Team A"},
            "team_b": {"id": TEAM_B, "name": "Team B"},
            "side_identity": {
                "status": "RESOLVED",
                "source": "fixture",
                "confidence": 1.0,
                "radiant_team_id": TEAM_A,
                "dire_team_id": TEAM_B,
                "blocker": None,
            },
            "series_context": {"best_of": 3, "map_number": 1},
        },
        market={
            "market_type": "Winner",
            "match_stage": "Map 1",
            "overround": 0.04,
            "quality": {"eligible": True, "warnings": [], "pair_skew_seconds": 0.2},
            "observations": [
                {
                    "selection_team_id": TEAM_A,
                    "price": 1.8,
                    "fair_probability": 0.54,
                    "implied_probability": 1 / 1.8,
                },
                {
                    "selection_team_id": TEAM_B,
                    "price": 2.0,
                    "fair_probability": 0.46,
                    "implied_probability": 0.5,
                },
            ],
        },
        draft={
            "complete": True,
            "warnings": [],
            "statistics_cutoff": NOW,
            "slots": [
                {
                    "side": "radiant",
                    "position": 1,
                    "hero_id": 1,
                    "source": "fixture",
                    "confidence": 1.0,
                }
            ],
            "curve": {
                "model_version": "fixture-v1",
                "points": [],
                "derived_features": {
                    "current_edge": 3.0,
                    "next_5m_edge": 2.0,
                    "next_10m_edge": 1.0,
                    "peak_edge": 3.0,
                    "peak_minute": 0,
                    "cross_over_minute": None,
                    "curve_slope_5m": -1.0,
                    "adjustment_delta": 0.5,
                    "fell_back_to_pure_score": False,
                    "decomposition": {"current": {}, "peak": {}},
                },
            },
        },
        history={
            "team_a": {
                "last_5": "4-1",
                "last_10": "7-3",
                "last_20": "14-6",
                "base_rating": 1520.0,
                "recent_form": 0.7,
                "roster_stability": 0.9,
                "exact_roster_maps": 18,
                "current_roster_strength": 0.68,
                "knowledge_cutoff": NOW,
            },
            "team_b": {
                "last_5": "3-2",
                "last_10": "6-4",
                "last_20": "11-9",
                "base_rating": 1490.0,
                "recent_form": 0.55,
                "roster_stability": 0.75,
                "exact_roster_maps": 12,
                "current_roster_strength": 0.59,
                "knowledge_cutoff": NOW,
            },
            "players_a": [
                {
                    "canonical_player_id": str(uuid4()),
                    "account_id": 1,
                    "position": 1,
                    "base_strength": 0.64,
                    "recent_form": 0.71,
                    "recent_form_confidence": 0.8,
                    "current_hero": 1,
                    "player_hero_strength": 0.76,
                    "player_hero_sample": 42,
                    "player_hero_confidence": 0.85,
                    "position_fit": 0.91,
                    "knowledge_cutoff": NOW,
                }
            ],
            "players_b": [],
            "coverage": {
                "team_strength_ready_count": 2,
                "roster_player_count": 1,
                "player_form_ready_count": 1,
                "player_hero_ready_count": 1,
            },
        },
        live={
            "game_time_seconds": 900,
            "radiant_kills": 10,
            "dire_kills": 7,
            "radiant_nw_lead": 1200,
            "first_blood": "radiant",
            "trend": {"windows": {}, "momentum_side_5m": "RADIANT"},
            "canvas": {},
            "charts": {},
            "enrichment": {},
            "field_freshness": {"complete": True, "effective_age_seconds": 2.0},
            "received_at": NOW,
        },
        quality={
            "eligible": True,
            "blockers": [],
            "warnings": [],
            "live_sync": "READY",
            "live_anchors": {"data_lag_seconds": 0.0},
        },
        snapshot_hash="context-profile-fixture",
    )
