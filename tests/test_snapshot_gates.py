from app.domain.snapshot import DecisionMode
from app.snapshots.gates import GateContext, evaluate_gate


def _context(**overrides: object) -> GateContext:
    values = {
        "identity_complete": True,
        "market_available": True,
        "market_pair_valid": True,
        "market_blockers": (),
        "market_warnings": (),
        "market_age_seconds": 1.0,
        "market_max_age_seconds": 30.0,
        "draft_available": True,
        "draft_complete": True,
        "historical_future_leak": False,
        "historical_blockers": (),
        "historical_warnings": (),
        "live_available": True,
        "live_message_age_seconds": 1.0,
        "live_age_seconds": 1.0,
        "live_max_age_seconds": 45.0,
        "live_sync_status": "SAFE",
        "live_sync_confidence": "HIGH",
    }
    values.update(overrides)
    return GateContext(**values)


def test_gate_selects_highest_safe_mode() -> None:
    result = evaluate_gate(_context())

    assert result.eligible is True
    assert result.mode is DecisionMode.LIVE_BASIC


def test_unsafe_live_degrades_to_post_draft() -> None:
    result = evaluate_gate(_context(live_sync_status="UNSAFE"))

    assert result.eligible is True
    assert result.mode is DecisionMode.POST_DRAFT
    assert "LIVE_DATA_DESYNC" in result.warnings


def test_low_confidence_safe_status_does_not_enable_live() -> None:
    result = evaluate_gate(_context(live_sync_confidence="LOW"))

    assert result.eligible is True
    assert result.mode is DecisionMode.POST_DRAFT
    assert "LIVE_DATA_DESYNC" in result.warnings


def test_partial_draft_degrades_to_prematch() -> None:
    result = evaluate_gate(_context(draft_complete=False))

    assert result.eligible is True
    assert result.mode is DecisionMode.PREMATCH
    assert "DRAFT_PARTIAL" in result.warnings


def test_stale_market_blocks_every_mode() -> None:
    result = evaluate_gate(_context(market_age_seconds=31.0))

    assert result.eligible is False
    assert result.blockers == ("MARKET_STALE",)


def test_invalid_market_pair_blocks_snapshot() -> None:
    result = evaluate_gate(
        _context(
            market_pair_valid=False,
            market_blockers=("MARKET_PAIR_TEAMS_MISMATCH",),
        )
    )

    assert result.eligible is False
    assert result.blockers == (
        "MARKET_PAIR_INVALID",
        "MARKET_PAIR_TEAMS_MISMATCH",
    )


def test_duplicate_live_messages_do_not_hide_stale_effective_state() -> None:
    result = evaluate_gate(_context(live_message_age_seconds=1.0, live_age_seconds=60.0))

    assert result.eligible is True
    assert result.mode is DecisionMode.POST_DRAFT
    assert "LIVE_STALE" in result.warnings
