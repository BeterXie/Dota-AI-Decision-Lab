from app.web.public_boundary import _sanitize_match_payload


def test_public_match_payload_strips_paid_ai_outputs_but_keeps_safe_readiness() -> None:
    payload = {
        "id": "map-1",
        "team_a": {"name": "Team Spirit"},
        "latest_snapshot": {
            "id": "snapshot-1",
            "decision_at": "2026-08-17T00:00:00Z",
            "created_at": "2026-08-17T00:00:01Z",
            "mode": "LIVE_BASIC",
            "snapshot_hash": "secret-input-hash",
            "market_quality": {"eligible": True},
            "history_coverage": {"maps": 100},
            "quality": {"eligible": True, "warnings": []},
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

    assert public["team_a"] == {"name": "Team Spirit"}
    assert public["decisions"] == []
    assert "checkpoint_decisions" not in public
    assert "snapshot_payload" not in public
    assert "future_odds" not in public
    assert "snapshot_hash" not in public["latest_snapshot"]
    assert public["latest_snapshot"]["quality"] == {"eligible": True, "warnings": []}
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
