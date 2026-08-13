from types import SimpleNamespace

from app.snapshots.side_aware import _live_window


def _row(game_time: int, *, lead: int, radiant_kills: int, dire_kills: int):
    return SimpleNamespace(
        game_time_seconds=game_time,
        radiant_nw_lead=lead,
        radiant_kills=radiant_kills,
        dire_kills=dire_kills,
    )


def test_live_window_uses_dota_game_time_and_required_tolerance() -> None:
    baseline = _row(600, lead=-1000, radiant_kills=5, dire_kills=6)
    current = _row(900, lead=2500, radiant_kills=10, dire_kills=7)

    window = _live_window([baseline, current], current=current, seconds=300)

    assert window["available"] is True
    assert window["effective_seconds"] == 300
    assert window["nw_delta"] == 3500
    assert window["nw_velocity_per_minute"] == 700.0
    assert window["radiant_kills_delta"] == 5
    assert window["dire_kills_delta"] == 1


def test_live_window_does_not_force_a_bad_baseline() -> None:
    old = _row(100, lead=-1000, radiant_kills=2, dire_kills=3)
    current = _row(900, lead=2500, radiant_kills=10, dire_kills=7)

    window = _live_window([old, current], current=current, seconds=300)

    assert window["available"] is False
    assert window["nw_delta"] is None
