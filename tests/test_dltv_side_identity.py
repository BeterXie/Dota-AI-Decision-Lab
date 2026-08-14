import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from app.providers.dltv.side_identity import MapSideAssignment, parse_side_evidence
from app.snapshots.side_aware import _align_history_to_series, _remove_unassigned_roster_history

FIXTURE = Path(__file__).parent / "fixtures" / "dltv_bootstrap.json"


def _payload() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_explicit_is_radiant_resolves_reversed_first_team_order() -> None:
    sides = parse_side_evidence(_payload())

    assert sides.resolved is True
    assert sides.radiant_provider_team_id == 502
    assert sides.dire_provider_team_id == 501
    assert sides.source == "DLTV_DB_IS_RADIANT"
    assert sides.confidence == 1.0


def test_missing_is_radiant_never_guesses_from_team_order() -> None:
    payload = _payload()
    del payload["db"]["first_team"]["is_radiant"]
    del payload["db"]["second_team"]["is_radiant"]

    sides = parse_side_evidence(payload)

    assert sides.resolved is False
    assert sides.radiant_provider_team_id is None
    assert sides.dire_provider_team_id is None


def test_radiant_team_b_roster_history_is_rebound_to_series_team_b() -> None:
    team_a_id = uuid4()
    team_b_id = uuid4()
    series = SimpleNamespace(team_a_id=team_a_id, team_b_id=team_b_id)
    assignment = MapSideAssignment(
        status="RESOLVED",
        radiant_team_id=team_b_id,
        dire_team_id=team_a_id,
        source="DLTV_DB_IS_RADIANT",
        confidence=1.0,
        observed_at=None,
        raw_event_id=None,
    )
    history = {
        "team_a": {"current_roster_strength": 200.0},
        "team_b": {"current_roster_strength": 100.0},
        "players_a": [{"canonical_player_id": "radiant-player"}],
        "players_b": [{"canonical_player_id": "dire-player"}],
    }

    _align_history_to_series(history, assignment, series)

    assert history["players_a"] == [{"canonical_player_id": "dire-player"}]
    assert history["players_b"] == [{"canonical_player_id": "radiant-player"}]
    assert history["team_a"]["current_roster_strength"] == 100.0
    assert history["team_b"]["current_roster_strength"] == 200.0


def test_unresolved_side_identity_removes_roster_specific_history() -> None:
    history = {
        "team_a": {"current_roster_strength": 100.0, "knowledge_cutoff": None},
        "team_b": {"current_roster_strength": 200.0, "knowledge_cutoff": None},
        "players_a": [{"canonical_player_id": "radiant-player"}],
        "players_b": [{"canonical_player_id": "dire-player"}],
        "coverage": {
            "roster_player_count": 10,
            "player_form_ready_count": 10,
            "player_hero_ready_count": 8,
            "earliest_knowledge_cutoff": None,
            "latest_knowledge_cutoff": None,
        },
    }

    _remove_unassigned_roster_history(history)

    assert history["players_a"] == []
    assert history["players_b"] == []
    assert history["team_a"]["current_roster_strength"] is None
    assert history["team_b"]["current_roster_strength"] is None
    assert history["coverage"]["roster_player_count"] == 0
    assert history["coverage"]["player_form_ready_count"] == 0
    assert history["coverage"]["player_hero_ready_count"] == 0
