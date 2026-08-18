from app.web.public_boundary import _sanitize_match_payload, _sanitize_runtime_payload


def test_public_match_payload_strips_paid_ai_outputs_and_nested_internal_fields() -> None:
    payload = {
        "id": "map-1",
        "team_a": {"id": "team-a", "name": "Team Spirit", "internal_rating": 9999},
        "team_b": {"id": "team-b", "name": "Falcons", "internal_rating": 8888},
        "series_maps": [
            {
                "canonical_map_id": "map-1",
                "map_number": 1,
                "valve_match_id": 123,
                "winner_team_id": None,
                "internal_series_signal": "secret",
            }
        ],
        "side_identity": {
            "status": "RESOLVED",
            "radiant_team_id": "team-a",
            "dire_team_id": "team-b",
            "source": "DLTV_DB_IS_RADIANT",
            "confidence": 1.0,
            "observed_at": "2026-08-17T00:00:00Z",
            "raw_event_id": "private-raw-event",
        },
        "market": [
            {
                "odds_id": 1,
                "selection_team_id": "team-a",
                "price": 1.8,
                "fair_probability": 0.54,
                "received_at": "2026-08-17T00:00:00Z",
                "age_seconds": 1.0,
                "internal_market_signal": "secret",
            }
        ],
        "draft": {
            "complete": True,
            "blockers": [],
            "warnings": [],
            "observed_at": "2026-08-17T00:00:00Z",
            "statistics_cutoff": "2026-08-16T23:59:00Z",
            "features": {
                "current_edge": 0.2,
                "next_5m_edge": 0.3,
                "player_analysis": {"private": True},
            },
            "curve": [
                {
                    "minute": 20,
                    "pure_radiant_edge": 0.2,
                    "adjusted_radiant_edge": 0.19,
                    "confidence": 0.8,
                    "private_point": "secret",
                }
            ],
            "model_version": "rosh-secret-v1",
            "data_version": "private-data-v1",
            "roster_ready_count": 10,
            "hero_ready_count": 10,
            "slots": [
                {
                    "side": "radiant",
                    "position": 1,
                    "account_id": 123,
                    "canonical_player_id": "player-1",
                    "player_name": "Carry",
                    "hero_id": 1,
                    "hero_name": "Hero",
                    "internal_slot_feature": 0.91,
                }
            ],
        },
        "live": {
            "game_time_seconds": 600,
            "radiant_kills": 8,
            "dire_kills": 6,
            "received_at": "2026-08-17T00:10:00Z",
            "last_message_received_at": "2026-08-17T00:10:00Z",
            "last_state_change_received_at": "2026-08-17T00:10:00Z",
            "connection_id": "c1",
            "reconnect_generation": 0,
            "internal_live_feature": "secret",
        },
        "latest_snapshot": {
            "id": "snapshot-1",
            "decision_at": "2026-08-17T00:00:00Z",
            "created_at": "2026-08-17T00:00:01Z",
            "mode": "LIVE_BASIC",
            "snapshot_hash": "secret-input-hash",
            "market_quality": {"eligible": True, "private_score": 0.9},
            "history_coverage": {"maps": 100, "private_strength": 1700},
            "quality": {
                "eligible": True,
                "warnings": [],
                "private_quality": "secret",
                "live_anchors": {
                    "raybet_live_anchor": "2026-08-17T00:00:00Z",
                    "data_lag_seconds": 12,
                    "private_anchor": "secret",
                },
            },
        },
        "result": {
            "winner_team_id": "team-a",
            "settled_at": "2026-08-17T01:00:00Z",
            "provider_conflict": False,
            "internal_result": "secret",
        },
        "decisions": [
            {
                "provider": "openai",
                "model": "gpt-5.6",
                "decision": {
                    "action": "BUY_A",
                    "confidence": 0.81,
                    "fair_probability_a": 0.64,
                    "primary_reasons": ["premium reason"],
                },
            },
            {
                "provider": "deepseek",
                "model": "deepseek-v4-pro",
                "decision": {"action": "PASS"},
            },
        ],
        "checkpoint_decisions": [{"decision": {"action": "BUY_B"}}],
        "snapshot_payload": {"frozen_ai_input": "paid"},
        "future_odds": [{"horizon_seconds": 60}],
    }

    public = _sanitize_match_payload(payload)

    assert public["team_a"] == {"id": "team-a", "name": "Team Spirit"}
    assert "internal_series_signal" not in public["series_maps"][0]
    assert "internal_market_signal" not in public["market"][0]
    assert public["side_identity"] == {
        "status": "RESOLVED",
        "radiant_team_id": "team-a",
        "dire_team_id": "team-b",
        "source": "DLTV_DB_IS_RADIANT",
        "confidence": 1.0,
        "observed_at": "2026-08-17T00:00:00Z",
    }
    assert public["draft"]["complete"] is True
    assert public["draft"]["features"] == {"current_edge": 0.2, "next_5m_edge": 0.3}
    assert public["draft"]["curve"] == [
        {
            "minute": 20,
            "pure_radiant_edge": 0.2,
            "adjusted_radiant_edge": 0.19,
            "confidence": 0.8,
        }
    ]
    assert "model_version" not in public["draft"]
    assert "data_version" not in public["draft"]
    assert "internal_slot_feature" not in public["draft"]["slots"][0]
    assert "internal_live_feature" not in public["live"]
    assert "internal_result" not in public["result"]
    assert public["decisions"] == []
    assert "checkpoint_decisions" not in public
    assert "snapshot_payload" not in public
    assert "future_odds" not in public
    assert "snapshot_hash" not in public["latest_snapshot"]
    assert "history_coverage" not in public["latest_snapshot"]
    assert "private_score" not in public["latest_snapshot"]["market_quality"]
    assert "private_quality" not in public["latest_snapshot"]["quality"]
    assert "private_anchor" not in public["latest_snapshot"]["quality"]["live_anchors"]
    assert public["ai_access"] == {
        "required_entitlement": "ai_decisions",
        "analysis_available": True,
        "updated_at": "2026-08-17T00:00:00Z",
        "completed_models": 2,
    }

    serialized = repr(public)
    assert "BUY_A" not in serialized
    assert "BUY_B" not in serialized
    assert "premium reason" not in serialized
    assert "fair_probability_a" not in serialized
    assert "rosh-secret-v1" not in serialized
    assert "private-data-v1" not in serialized


def test_anonymous_runtime_projection_hides_operational_diagnostics() -> None:
    public = _sanitize_runtime_payload(
        {
            "overall": "DEGRADED",
            "observed_at": "2026-08-17T00:00:00Z",
            "live_state_max_age_seconds": 120,
            "live_market_max_age_seconds": 90,
            "workers": {
                "AIWorker": {"last_error": "provider secret failure", "metadata": {"jobs": 4}}
            },
            "dependencies": {"GPT": {"status": "FAILED", "last_error": "private provider error"}},
            "new_internal_runtime_field": "secret",
        }
    )

    assert public == {
        "overall": "DEGRADED",
        "observed_at": "2026-08-17T00:00:00Z",
        "live_state_max_age_seconds": 120,
        "live_market_max_age_seconds": 90,
        "workers": {},
        "dependencies": {},
    }
