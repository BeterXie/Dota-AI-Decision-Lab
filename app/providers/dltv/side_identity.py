from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class DltvSideEvidence:
    radiant_provider_team_id: int | None
    dire_provider_team_id: int | None
    source: str | None
    confidence: float | None

    @property
    def resolved(self) -> bool:
        return self.radiant_provider_team_id is not None and self.dire_provider_team_id is not None


def parse_side_evidence(payload: dict[str, Any]) -> DltvSideEvidence:
    database = payload.get("db")
    if not isinstance(database, dict):
        return _unresolved()
    first_team = database.get("first_team")
    second_team = database.get("second_team")
    if not isinstance(first_team, dict) or not isinstance(second_team, dict):
        return _unresolved()
    first_id = _team_id(first_team)
    second_id = _team_id(second_team)
    first_is_radiant = first_team.get("is_radiant")
    second_is_radiant = second_team.get("is_radiant")
    if (
        first_id is None
        or second_id is None
        or not isinstance(first_is_radiant, bool)
        or not isinstance(second_is_radiant, bool)
        or first_is_radiant == second_is_radiant
    ):
        return _unresolved()
    if first_is_radiant:
        radiant_id, dire_id = first_id, second_id
    else:
        radiant_id, dire_id = second_id, first_id
    return DltvSideEvidence(
        radiant_provider_team_id=radiant_id,
        dire_provider_team_id=dire_id,
        source="DLTV_DB_IS_RADIANT",
        confidence=1.0,
    )


def _team_id(team: dict[str, Any]) -> int | None:
    value = team.get("id")
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _unresolved() -> DltvSideEvidence:
    return DltvSideEvidence(
        radiant_provider_team_id=None,
        dire_provider_team_id=None,
        source=None,
        confidence=None,
    )
