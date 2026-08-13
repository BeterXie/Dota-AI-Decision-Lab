from app.draft.rosh_service import _decomposition_summary


def test_rosh_decomposition_preserves_current_and_peak_components() -> None:
    result = {
        "minute_table": [
            {
                "minute": 20,
                "win_rate_graph": 2.0,
                "hero_base_adjustment": 1.0,
                "hero_tempo_adjustment": 0.5,
                "synergy_adjustment": 0.2,
                "player_adjustment": 0.3,
                "hero_adjustment": 1.5,
            },
            {
                "minute": 30,
                "win_rate_graph": -6.0,
                "hero_base_adjustment": -1.0,
                "hero_tempo_adjustment": -2.0,
                "synergy_adjustment": -1.5,
                "player_adjustment": -1.5,
                "hero_adjustment": -3.0,
            },
        ]
    }

    summary = _decomposition_summary(result, current_minute=22)

    assert summary["current_minute"] == 20
    assert summary["current"]["hero_base_adjustment"] == 1.0
    assert summary["current"]["player_adjustment"] == 0.3
    assert summary["peak_minute"] == 30
    assert summary["peak"]["hero_tempo_adjustment"] == -2.0
    assert summary["peak"]["synergy_adjustment"] == -1.5
