import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from app.replay import RecordedEvent, ReplayHarness

FIXTURES = Path(__file__).parent / "fixtures"
MAP_ID = UUID("11111111-1111-1111-1111-111111111111")
VALVE_MATCH_ID = 8940730389


def _recorded_payload(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _market_payload(price: str, *, status: int = 1) -> dict:
    payload = _recorded_payload("raybet_socket_odds.json")
    payload["data"]["data"]["odds"][0]["odds"] = price
    payload["data"]["data"]["odds"][0]["status"] = status
    return payload


def _live_payload(game_time: int, kills: int, lead: int) -> dict:
    return {
        "game_time": game_time,
        "radiant_score": kills,
        "dire_score": kills - 1,
        "radiant_lead": lead,
    }


def _timeline() -> list[RecordedEvent]:
    start = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)
    bootstrap = _recorded_payload("dltv_bootstrap.json")
    items = [
        (
            "history",
            "history",
            "HISTORICAL_SNAPSHOT",
            0,
            {
                "knowledge_cutoff": start.isoformat(),
                "features": {"team_a_elo": 1602.0, "team_b_elo": 1541.0},
            },
        ),
        ("draft", "dltv", "DLTV_BOOTSTRAP", 1, bootstrap),
        ("market-0", "raybet", "RAYBET_SOCKET_ODDS", 2, _market_payload("2.00")),
        ("live-0", "dltv", "DLTV_FAST_SOCKET", 3, _live_payload(900, 8, 100)),
        ("market-1", "raybet", "RAYBET_SOCKET_ODDS", 10, _market_payload("2.20")),
        ("live-1", "dltv", "DLTV_FAST_SOCKET", 11, _live_payload(910, 9, 700)),
        ("market-2", "raybet", "RAYBET_SOCKET_ODDS", 20, _market_payload("2.00")),
        ("live-2", "dltv", "DLTV_FAST_SOCKET", 21, _live_payload(920, 10, 1300)),
        ("market-3", "raybet", "RAYBET_SOCKET_ODDS", 30, _market_payload("2.20")),
        ("live-3", "dltv", "DLTV_FAST_SOCKET", 31, _live_payload(930, 11, 1900)),
        ("checkpoint", "system", "DECISION_CHECKPOINT", 32, {}),
    ]
    return [
        RecordedEvent(
            event_id=event_id,
            provider=provider,
            event_type=event_type,
            received_at=start + timedelta(seconds=offset),
            payload=payload,
        )
        for event_id, provider, event_type, offset, payload in items
    ]


def test_replay_is_deterministic_across_restart_and_duplicate_delivery() -> None:
    events = _timeline()
    baseline = ReplayHarness(MAP_ID, valve_match_id=VALVE_MATCH_ID).replay(events)
    restarted = ReplayHarness(MAP_ID, valve_match_id=VALVE_MATCH_ID).replay(events, restart_after=6)
    duplicate = ReplayHarness(MAP_ID, valve_match_id=VALVE_MATCH_ID).replay(
        [*events[:5], events[4], *events[5:]]
    )

    assert baseline.snapshots[0].mode == "LIVE_BASIC"
    assert baseline.snapshots[0].snapshot_hash == restarted.snapshots[0].snapshot_hash
    assert baseline.snapshots[0].snapshot_hash == duplicate.snapshots[0].snapshot_hash
    assert baseline.normalized_live_updates == restarted.normalized_live_updates
    assert duplicate.raw_event_count == baseline.raw_event_count + 1
    assert duplicate.normalized_market_updates == baseline.normalized_market_updates


def test_replay_preserves_order_blocks_future_history_and_degrades_provider_gap() -> None:
    start = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)
    bootstrap = _recorded_payload("dltv_bootstrap.json")
    events = [
        RecordedEvent(
            event_id="draft",
            provider="dltv",
            event_type="DLTV_BOOTSTRAP",
            received_at=start,
            payload=bootstrap,
        ),
        RecordedEvent(
            event_id="market",
            provider="raybet",
            event_type="RAYBET_SOCKET_ODDS",
            received_at=start + timedelta(seconds=1),
            payload=_market_payload("2.00"),
        ),
        RecordedEvent(
            event_id="future-history",
            provider="history",
            event_type="HISTORICAL_SNAPSHOT",
            received_at=start + timedelta(seconds=2),
            payload={
                "knowledge_cutoff": (start + timedelta(minutes=10)).isoformat(),
                "features": {"future_fact": True},
            },
        ),
        RecordedEvent(
            event_id="live",
            provider="dltv",
            event_type="DLTV_FAST_SOCKET",
            received_at=start + timedelta(seconds=3),
            payload=_live_payload(60, 1, 100),
        ),
        RecordedEvent(
            event_id="checkpoint",
            provider="system",
            event_type="DECISION_CHECKPOINT",
            received_at=start + timedelta(seconds=4),
            payload={},
        ),
    ]

    result = ReplayHarness(MAP_ID, valve_match_id=VALVE_MATCH_ID).replay(events)
    snapshot = result.snapshots[0]

    assert result.processed_event_ids == tuple(event.event_id for event in events)
    assert snapshot.mode == "POST_DRAFT"
    assert "HISTORICAL_DATA_FUTURE_LEAK" in snapshot.canonical_payload["quality"]["blockers"]
    assert "LIVE_SYNC_UNKNOWN" in snapshot.canonical_payload["quality"]["warnings"]
