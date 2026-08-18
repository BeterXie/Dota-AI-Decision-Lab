from app.entitlements import (
    AI_DECISIONS_ENTITLEMENT,
)
from app.notifications.pairing_limiter import PairingAttemptLimiter
from app.web.auth import _http_access_requirement
from app.web.public_boundary import _sanitize_match_payload


def test_http_access_policy_is_explicit_and_unknown_api_is_not_public() -> None:
    assert _http_access_requirement("/api/matches") == ("PUBLIC", None)
    assert _http_access_requirement("/api/teams") == ("PUBLIC", None)
    assert _http_access_requirement("/api/teams/00000000-0000-0000-0000-000000000000") == (
        "PUBLIC",
        None,
    )
    assert _http_access_requirement("/api/maps/00000000-0000-0000-0000-000000000000") == (
        "PUBLIC",
        None,
    )
    assert _http_access_requirement(
        "/api/maps/00000000-0000-0000-0000-000000000000/draft-hero-recent"
    ) == ("PUBLIC", None)
    # Map AI is public only after the route confirms a settled map result;
    # in-progress requests still require authentication or a scoped grant.
    assert _http_access_requirement(
        "/api/maps/00000000-0000-0000-0000-000000000000/ai-decisions"
    ) == ("PUBLIC", None)
    assert _http_access_requirement("/api/review") == ("PUBLIC", None)
    assert _http_access_requirement("/api/ai-performance") == ("PUBLIC", None)
    assert _http_access_requirement("/api/snapshots") == (
        "ENTITLED",
        AI_DECISIONS_ENTITLEMENT,
    )
    # Notification Center also accepts scoped realtime grants, so middleware
    # authenticates and the router performs the resource-aware grant check.
    assert _http_access_requirement("/api/notifications") == (
        "AUTHENTICATED",
        None,
    )
    assert _http_access_requirement("/api/billing/offers") == ("PUBLIC", None)
    assert _http_access_requirement("/api/billing/webhooks/paddle") == ("PUBLIC", None)
    assert _http_access_requirement("/api/billing/account") == ("AUTHENTICATED", None)
    assert _http_access_requirement(
        "/api/billing/series/00000000-0000-0000-0000-000000000000/checkout"
    ) == ("AUTHENTICATED", None)
    assert _http_access_requirement(
        "/api/billing/events/00000000-0000-0000-0000-000000000000/checkout"
    ) == ("AUTHENTICATED", None)
    assert _http_access_requirement("/api/future-ai-export") == ("AUTHENTICATED", None)


def test_public_match_projection_drops_new_fields_by_default() -> None:
    payload = {
        "entity_type": "MAP",
        "id": "map-1",
        "team_a": {"id": "a", "name": "A"},
        "team_b": {"id": "b", "name": "B"},
        "latest_snapshot": {
            "id": "snapshot-1",
            "decision_at": "2026-08-17T00:00:00Z",
            "snapshot_hash": "private-hash",
        },
        "decisions": [{"provider": "openai", "model": "gpt", "decision": {"action": "BUY_A"}}],
        "model_consensus": {"action": "BUY_A", "confidence": 0.91},
        "new_internal_ai_field": "must-not-leak",
    }

    public = _sanitize_match_payload(payload)

    assert public["id"] == "map-1"
    assert public["decisions"] == []
    assert public["latest_snapshot"] == {
        "id": "snapshot-1",
        "decision_at": "2026-08-17T00:00:00Z",
    }
    assert "model_consensus" not in public
    assert "new_internal_ai_field" not in public
    assert "snapshot_hash" not in public["latest_snapshot"]


def test_pairing_attempt_limiter_blocks_bursts_per_destination() -> None:
    limiter = PairingAttemptLimiter(max_attempts=2, window_seconds=60)
    assert limiter.allow("QQ:c2c:user-1") is True
    assert limiter.allow("QQ:c2c:user-1") is True
    assert limiter.allow("QQ:c2c:user-1") is False
    assert limiter.allow("QQ:c2c:user-2") is True
