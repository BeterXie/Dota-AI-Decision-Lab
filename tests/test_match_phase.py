from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from app.web.api import _match_phase


def test_fresh_live_state_wins_over_unconfirmed_result() -> None:
    observed_at = datetime.now(UTC)
    live = SimpleNamespace(
        game_time_seconds=120,
        last_message_received_at=observed_at - timedelta(seconds=5),
        last_state_change_received_at=observed_at - timedelta(seconds=4),
    )
    result = SimpleNamespace(winner_team_id=None, provider_conflict=False)

    assert (
        _match_phase(
            scheduled_at=None,
            live=live,
            result=result,
            observed_at=observed_at,
            live_state_max_age_seconds=45,
        )
        == "LIVE"
    )


def test_confirmed_result_wins_over_fresh_live_state() -> None:
    observed_at = datetime.now(UTC)
    live = SimpleNamespace(
        game_time_seconds=120,
        last_message_received_at=observed_at - timedelta(seconds=5),
        last_state_change_received_at=observed_at - timedelta(seconds=4),
    )
    result = SimpleNamespace(winner_team_id="team-a", provider_conflict=False)

    assert (
        _match_phase(
            scheduled_at=None,
            live=live,
            result=result,
            observed_at=observed_at,
            live_state_max_age_seconds=45,
        )
        == "POSTMATCH"
    )


def test_past_schedule_without_started_live_state_is_delayed_start() -> None:
    observed_at = datetime.now(UTC)
    pregame = SimpleNamespace(
        game_time_seconds=None,
        last_message_received_at=observed_at - timedelta(seconds=5),
        last_state_change_received_at=observed_at - timedelta(seconds=5),
    )

    assert (
        _match_phase(
            scheduled_at=observed_at - timedelta(minutes=30),
            live=pregame,
            result=None,
            observed_at=observed_at,
            live_state_max_age_seconds=45,
        )
        == "DELAYED_START"
    )


def test_started_match_with_stale_live_state_remains_live_but_delayed() -> None:
    observed_at = datetime.now(UTC)
    stale_live = SimpleNamespace(
        game_time_seconds=720,
        last_message_received_at=observed_at - timedelta(seconds=5),
        last_state_change_received_at=observed_at - timedelta(seconds=90),
    )

    assert (
        _match_phase(
            scheduled_at=observed_at - timedelta(hours=1),
            live=stale_live,
            result=None,
            observed_at=observed_at,
            live_state_max_age_seconds=45,
        )
        == "LIVE_DATA_DELAYED"
    )
