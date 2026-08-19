from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from app.web.api import _match_phase


def test_fresh_live_state_wins_over_unconfirmed_result() -> None:
    observed_at = datetime.now(UTC)
    live = SimpleNamespace(last_message_received_at=observed_at - timedelta(seconds=5))
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
    live = SimpleNamespace(last_message_received_at=observed_at - timedelta(seconds=5))
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
