import pytest

from app.draft.engine import MODEL_VERSION, score_rosh_lineups
from app.providers.stratz.draft_queries import REFERENCE_COMMIT


def _reference_analysis() -> dict:
    meta: dict[str, list[dict]] = {"heroes": []}
    by_time: dict[str, list[dict]] = {}
    for position in range(1, 6):
        radiant_hero = position
        dire_hero = 100 + position
        meta[f"heroesPos_{position}"] = [
            {"heroId": radiant_hero, "matchCount": 1000, "winCount": 550},
            {"heroId": dire_hero, "matchCount": 1000, "winCount": 450},
        ]
        rows = []
        for minute in range(20, 61):
            remaining = 61 - minute
            rows.extend(
                (
                    {
                        "heroId": radiant_hero,
                        "time": minute,
                        "matchCount": remaining * 100,
                        "winCount": remaining * 55,
                    },
                    {
                        "heroId": dire_hero,
                        "time": minute,
                        "matchCount": remaining * 100,
                        "winCount": remaining * 45,
                    },
                )
            )
        by_time[f"heroStatsByTime_{position}"] = rows
    synergy = {
        "matchUp_Prev_Week_1": [
            {
                "heroId": 1,
                "with": [{"heroId2": 2, "synergy": 2.0, "matchCount": 100}],
                "vs": [{"heroId2": 101, "synergy": 1.5, "matchCount": 100}],
            },
            {
                "heroId": 2,
                "with": [{"heroId2": 1, "synergy": 2.0, "matchCount": 100}],
                "vs": [],
            },
            {
                "heroId": 101,
                "with": [{"heroId2": 102, "synergy": 0.5, "matchCount": 100}],
                "vs": [{"heroId2": 1, "synergy": -0.5, "matchCount": 100}],
            },
            {
                "heroId": 102,
                "with": [{"heroId2": 101, "synergy": 0.5, "matchCount": 100}],
                "vs": [],
            },
        ]
    }
    return {
        "heroes_meta_positions": meta,
        "hero_stats_by_time_bracket": by_time,
        "synergy": synergy,
    }


def _highlight(*, matches: int, wins: int, recent_matches: int, recent_wins: int) -> dict:
    return {
        "matchCount": matches,
        "winCount": wins,
        "impAllTime": 0,
        "matchCountLastMonth": recent_matches,
        "winCountLastMonth": recent_wins,
        "impLastMonth": 10 if matches >= 30 and wins > matches / 2 else 0,
        "matchCountLastSixMonths": recent_matches,
        "winCountLastSixMonths": recent_wins,
        "impLastSixMonths": 0,
    }


def test_rosh_matches_pinned_reference_curve_and_high_sample_adjustment() -> None:
    result = score_rosh_lineups(
        [1, 2, 3, 4, 5],
        [101, 102, 103, 104, 105],
        _reference_analysis(),
        radiant_player_highlights=[
            _highlight(matches=30, wins=21, recent_matches=10, recent_wins=7) for _ in range(5)
        ],
        dire_player_highlights=[
            _highlight(matches=30, wins=15, recent_matches=10, recent_wins=5) for _ in range(5)
        ],
    )

    assert REFERENCE_COMMIT == "c7a54b59299fb6f46988cb85ed85ebacfe9c0f04"
    assert MODEL_VERSION == "rosh-c7a54b5-v1"
    assert [row["minute"] for row in result["pure_minute_table"]] == list(range(20, 61))
    assert {row["win_rate_graph"] for row in result["pure_minute_table"]} == {15.8}
    assert {row["win_rate_graph"] for row in result["minute_table"]} == {17.3}
    assert result["pure_minute_table"][0]["synergy_adjustment"] == 2.5
    assert result["player_analysis"]["netAdjustment"] == 1.5
    assert result["used_player_adjustment"] is True
    assert result["fell_back_to_pure_score"] is False


def test_rosh_small_player_sample_is_bounded_and_missing_data_falls_back() -> None:
    analysis = _reference_analysis()
    low_sample = score_rosh_lineups(
        [1, 2, 3, 4, 5],
        [101, 102, 103, 104, 105],
        analysis,
        radiant_player_highlights=[
            _highlight(matches=3, wins=3, recent_matches=3, recent_wins=3),
            None,
            None,
            None,
            None,
        ],
        dire_player_highlights=[None] * 5,
    )
    fallback = score_rosh_lineups(
        [1, 2, 3, 4, 5],
        [101, 102, 103, 104, 105],
        analysis,
        radiant_player_highlights=[None] * 5,
        dire_player_highlights=[None] * 5,
    )

    assert low_sample["player_analysis"]["netAdjustment"] == pytest.approx(0.2)
    assert low_sample["player_adjusted_lineup_score"] == pytest.approx(16.0)
    assert fallback["player_adjusted_lineup_score"] == fallback["pure_lineup_score"]
    assert fallback["fell_back_to_pure_score"] is True


def test_rosh_partial_time_payload_stays_unknown() -> None:
    analysis = _reference_analysis()
    analysis["hero_stats_by_time_bracket"] = {}

    result = score_rosh_lineups(
        [1, 2, 3, 4, 5],
        [101, 102, 103, 104, 105],
        analysis,
    )

    assert result["pure_minute_table"] == []
    assert result["minute_table"] == []
    assert result["pure_lineup_score"] is None
    assert result["player_adjusted_lineup_score"] is None
