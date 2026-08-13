import json
from pathlib import Path

from app.providers.dltv.side_identity import parse_side_evidence

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
