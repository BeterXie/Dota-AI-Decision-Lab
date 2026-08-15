from datetime import datetime
from typing import Any

from app.domain.history import HistoricalMap, HistoricalMatchBundle
from app.providers.common import TimedPayload
from app.providers.dltv.bootstrap import DltvBootstrapClient

NORMALIZER_VERSION = "dltv-result-v1"


class DltvResultProvider:
    """Basic postmatch result source backed by the existing DLTV live endpoint.

    ``GET /live/{valve_match_id}.json`` publishes ``winner: "radiant" | "dire"``
    once the map is over.  The winner side is mapped to a provider team id
    exclusively through the explicit ``db.first_team.is_radiant`` /
    ``db.second_team.is_radiant`` booleans; DLTV provider ordering is never
    treated as Radiant/Dire.
    """

    name = "dltv"
    normalizer_version = NORMALIZER_VERSION

    def __init__(self, client: DltvBootstrapClient) -> None:
        self._client = client

    async def get_match_advanced(self, match_id: int) -> TimedPayload:
        return await self._client.get_live(match_id)

    def normalize_match(self, payload: dict, *, fetched_at: datetime) -> HistoricalMatchBundle:
        return normalize_match_result(payload, fetched_at=fetched_at)


def normalize_match_result(
    payload: dict[str, Any],
    *,
    fetched_at: datetime,
) -> HistoricalMatchBundle:
    match_id = _required_int(payload, "match_id")
    database = payload.get("db")
    if not isinstance(database, dict):
        raise ValueError("DLTV result payload is missing db identity")
    first_team = database.get("first_team")
    second_team = database.get("second_team")
    first_id = _team_id(first_team)
    second_id = _team_id(second_team)
    first_radiant = first_team.get("is_radiant") if isinstance(first_team, dict) else None
    second_radiant = second_team.get("is_radiant") if isinstance(second_team, dict) else None
    if (
        first_id is None
        or second_id is None
        or not isinstance(first_radiant, bool)
        or not isinstance(second_radiant, bool)
        or first_radiant == second_radiant
    ):
        raise ValueError("DLTV result side identity is incomplete")
    radiant_team_id = first_id if first_radiant else second_id
    dire_team_id = second_id if first_radiant else first_id

    winner_side = payload.get("winner")
    if not isinstance(winner_side, str) or winner_side.casefold() not in {"radiant", "dire"}:
        raise ValueError("winner is not published")
    winner_team_id = radiant_team_id if winner_side.casefold() == "radiant" else dire_team_id

    series = database.get("series") if isinstance(database.get("series"), dict) else {}
    published_started_at = _iso_datetime(series.get("started_at"))
    started_at = published_started_at or fetched_at
    started_at_estimated = published_started_at is None
    ended_at = _iso_datetime(series.get("ended_at"))
    match = HistoricalMap(
        provider_match_id=str(match_id),
        event_id=_optional_id(series.get("event_id")),
        patch_id=None,
        started_at=started_at,
        started_at_estimated=started_at_estimated,
        ended_at=ended_at,
        radiant_team_id=str(radiant_team_id),
        dire_team_id=str(dire_team_id),
        winner_team_id=str(winner_team_id),
        duration_seconds=_optional_nonnegative_int(payload.get("game_time")),
        provider="dltv",
        first_usable_at=fetched_at,
        fetched_at=fetched_at,
    )
    return HistoricalMatchBundle(
        match=match,
        players=(),
        advanced_available=False,
        warnings=("STARTED_AT_ESTIMATED_FROM_FETCHED_AT",) if started_at_estimated else (),
    )


def _team_id(team: object) -> int | None:
    value = team.get("id") if isinstance(team, dict) else None
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _required_int(payload: dict[str, Any], key: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"DLTV result field {key} is required")
    return value


def _optional_nonnegative_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _optional_id(value: object) -> str | None:
    parsed = _optional_nonnegative_int(value)
    return str(parsed) if parsed is not None else None


def _iso_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
