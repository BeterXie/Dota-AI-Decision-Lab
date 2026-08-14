import json
from pathlib import Path

from app.providers.dltv.parser import parse_fast_patch, parse_live_enrichment


def test_fast_patch_parses_canvas_and_charts() -> None:
    payload = {
        "match_id": 8940730389,
        "game_time": 2507,
        "radiant_score": 30,
        "dire_score": 32,
        "radiant_lead": 13871,
        "first_blood": "dire",
        "canvas": {"radiant": ["b1", "m1", "t1"], "dire": ["t1", "t2", "mR", "mM"]},
        "charts": {
            "game_times": [0, 146, 153],
            "net_worth": [0, -428, -155],
            "radiant_scores": [0, 1, 1],
            "dire_scores": [0, 0, 1],
            "radiant_kills": [0, 1, 1],
            "dire_kills": [0, 0, 1],
        },
    }
    patch = parse_fast_patch(
        payload,
        valve_match_id=8940730389,
        received_at=__import__("datetime").datetime(2026, 8, 14, tzinfo=__import__("datetime").UTC),
    )

    assert patch.updates["canvas"] == {
        "radiant": ["b1", "m1", "t1"],
        "dire": ["t1", "t2", "mR", "mM"],
    }
    assert patch.updates["charts"]["net_worth"] == [0, -428, -155]
    assert patch.updates["game_time_seconds"] == 2507


def test_live_enrichment_parses_full_stats_and_bans() -> None:
    payload = json.loads(
        (Path(__file__).parent / "fixtures" / "dltv_bootstrap.json").read_text(encoding="utf-8")
    )
    payload["full_stats"] = {
        "radiant": {
            "players": [
                {
                    "player": {"steam_id": 1001, "title": "Player One"},
                    "level": 12,
                    "kda": "4 / 2 / 9",
                    "items": [116, -1, -1, -1, -1, -1],
                    "gold": 1234,
                    "lh": "88 / 4",
                    "gpm": "520 / 610",
                    "net_worth": 7800,
                }
            ]
        },
        "dire": {"players": []},
    }
    payload["db"]["first_team"]["bans"] = [{"hero_id": 83}, {"hero_id": 121}]
    payload["db"]["second_team"]["bans"] = [{"hero": {"steam_id": 25}}]

    enrichment = parse_live_enrichment(payload)

    assert enrichment["bans"] == {"radiant": [83, 121], "dire": [25]}
    player = enrichment["full_stats"][0]
    assert player["account_id"] == 1001
    assert player["kda"] == {"kills": 4, "deaths": 2, "assists": 9}
    assert player["items"] == [116]
    assert player["lh"] == {"first": 88, "second": 4}
    assert player["gpm"] == {"first": 520, "second": 610}
    assert player["net_worth"] == 7800


def test_live_enrichment_ignores_malformed_entries() -> None:
    enrichment = parse_live_enrichment(
        {
            "full_stats": {
                "radiant": {
                    "players": [
                        {"player": "not-a-dict", "level": 3, "net_worth": 100},
                        {"player": {"steam_id": 1002}, "kda": "bad"},
                    ]
                }
            },
            "db": {
                "first_team": {"bans": [{"hero_id": "not-an-int"}]},
                "second_team": {"bans": [{"hero_id": 0}]},
            },
        }
    )

    assert enrichment["bans"] == {"radiant": [], "dire": []}
    assert len(enrichment["full_stats"]) == 1
    assert enrichment["full_stats"][0]["account_id"] == 1002
    assert enrichment["full_stats"][0]["kda"] is None
