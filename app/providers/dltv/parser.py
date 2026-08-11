from datetime import datetime
from typing import Any

from app.canonical import content_digest
from app.domain.draft import DraftSlot, DraftValidation
from app.domain.live import DltvFastState
from app.providers.dltv.models import DltvBootstrapIdentity, DltvSeries, DltvSeriesFrame

PARSER_VERSION = "dltv-v1"


def parse_series_frame(payload: dict[str, Any]) -> DltvSeriesFrame:
    raw_live = payload.get("live")
    live_maps: dict[int, int] = {}
    if isinstance(raw_live, dict):
        for match_id, series_id in raw_live.items():
            try:
                parsed_match_id = int(match_id)
            except TypeError, ValueError:
                continue
            if _is_int(series_id):
                live_maps[parsed_match_id] = series_id

    series_by_id: dict[int, DltvSeries] = {}
    for collection_name in ("upcoming", "results"):
        collection = payload.get(collection_name)
        for item in collection if isinstance(collection, list) else []:
            if not isinstance(item, dict):
                continue
            series_id = item.get("id")
            first_team_id = item.get("first_team_id")
            second_team_id = item.get("second_team_id")
            if not all(_is_int(value) for value in (series_id, first_team_id, second_team_id)):
                continue
            scores = item.get("series_scores")
            series_by_id[series_id] = DltvSeries(
                series_id=series_id,
                event_id=_optional_int(item.get("event_id")),
                first_team_id=first_team_id,
                second_team_id=second_team_id,
                started_at=_parse_iso_datetime(item.get("started_at")),
                status=_optional_int(item.get("status")),
                first_team_score=(
                    _optional_int(scores.get("first_team")) if isinstance(scores, dict) else None
                ),
                second_team_score=(
                    _optional_int(scores.get("second_team")) if isinstance(scores, dict) else None
                ),
            )
    return DltvSeriesFrame(live_maps=live_maps, series=tuple(series_by_id.values()))


def parse_bootstrap_identity(
    payload: dict[str, Any], *, valve_match_id: int
) -> DltvBootstrapIdentity:
    database = payload.get("db")
    if not isinstance(database, dict):
        raise ValueError("DLTV bootstrap is missing db identity")
    first_team = database.get("first_team")
    second_team = database.get("second_team")
    series = database.get("series")
    if not _valid_team(first_team) or not _valid_team(second_team):
        raise ValueError("DLTV bootstrap team identity is incomplete")
    series_id = _optional_int(series.get("id")) if isinstance(series, dict) else None
    event_id = _optional_int(series.get("event_id")) if isinstance(series, dict) else None
    started_at = _parse_iso_datetime(series.get("started_at")) if isinstance(series, dict) else None
    scores = database.get("scores")
    first_score = second_score = None
    if isinstance(scores, dict):
        first_score = _optional_int(scores.get("first_team", scores.get("firstTeam")))
        second_score = _optional_int(scores.get("second_team", scores.get("secondTeam")))
    if first_score is None or second_score is None:
        series_scores = series.get("series_scores") if isinstance(series, dict) else None
        if isinstance(series_scores, dict):
            first_score = _optional_int(series_scores.get("first_team"))
            second_score = _optional_int(series_scores.get("second_team"))
    map_number = (
        first_score + second_score + 1
        if first_score is not None and second_score is not None
        else None
    )
    return DltvBootstrapIdentity(
        valve_match_id=valve_match_id,
        series_id=series_id,
        event_id=event_id,
        first_team_id=first_team["id"],
        first_team_name=first_team["title"],
        second_team_id=second_team["id"],
        second_team_name=second_team["title"],
        started_at=started_at,
        map_number=map_number,
    )


def parse_draft(payload: dict[str, Any]) -> DraftValidation:
    players = payload.get("players")
    blockers: list[str] = []
    warnings: list[str] = []
    slots: list[DraftSlot] = []
    if not isinstance(players, list) or len(players) != 10:
        blockers.append("DRAFT_PARTIAL")
        return DraftValidation(complete=False, slots=(), blockers=tuple(blockers))

    for player in players:
        if not isinstance(player, dict):
            blockers.append("DRAFT_PARTIAL")
            continue
        hero_id = player.get("hero_id")
        team = player.get("team")
        position = player.get("team_slot")
        if (
            not _is_int(hero_id)
            or hero_id <= 0
            or team not in (0, 1)
            or not _is_int(position)
            or position not in range(1, 6)
        ):
            blockers.append("DRAFT_PARTIAL")
            continue
        account_id = player.get("account_id")
        slots.append(
            DraftSlot(
                side="radiant" if team == 0 else "dire",
                position=position,
                account_id=account_id if _is_int(account_id) else None,
                hero_id=hero_id,
                source="DLTV_SLOT",
                confidence=1.0,
            )
        )

    if len(slots) != 10:
        blockers.append("DRAFT_PARTIAL")
    if len({slot.hero_id for slot in slots}) != 10:
        blockers.append("DRAFT_HERO_DUPLICATE")
    for side in ("radiant", "dire"):
        side_slots = [slot for slot in slots if slot.side == side]
        if len(side_slots) != 5 or {slot.position for slot in side_slots} != set(range(1, 6)):
            blockers.append("DRAFT_SLOT_INVALID")
    if any(slot.account_id is None for slot in slots):
        warnings.append("ROSTER_IDENTITY_PARTIAL")
    return DraftValidation(
        complete=not blockers,
        slots=tuple(sorted(slots, key=lambda slot: (slot.side, slot.position))),
        blockers=tuple(dict.fromkeys(blockers)),
        warnings=tuple(dict.fromkeys(warnings)),
    )


def parse_fast_state(
    payload: dict[str, Any], *, valve_match_id: int, received_at: datetime
) -> DltvFastState:
    game_time = _optional_nonnegative_int(payload.get("game_time"))
    state_values = {
        "game_time": game_time,
        "radiant_score": _optional_nonnegative_int(payload.get("radiant_score")),
        "dire_score": _optional_nonnegative_int(payload.get("dire_score")),
        "radiant_lead": _optional_int(payload.get("radiant_lead")),
        "first_blood": payload.get("first_blood")
        if isinstance(payload.get("first_blood"), str)
        else None,
    }
    return DltvFastState(
        valve_match_id=valve_match_id,
        game_time_seconds=game_time,
        radiant_kills=state_values["radiant_score"],
        dire_kills=state_values["dire_score"],
        radiant_nw_lead=state_values["radiant_lead"],
        first_blood=state_values["first_blood"],
        source_game_time=game_time,
        received_at=received_at,
        payload_hash=content_digest(state_values),
    )


def delayed_detail_is_fresh(payload: dict[str, Any], *, max_delay_seconds: float) -> bool:
    live_data = payload.get("live_league_data")
    if not isinstance(live_data, dict):
        return False
    delay = live_data.get("stream_delay_s")
    return (
        isinstance(delay, (int, float))
        and not isinstance(delay, bool)
        and delay <= max_delay_seconds
    )


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _optional_int(value: object) -> int | None:
    return value if _is_int(value) else None


def _optional_nonnegative_int(value: object) -> int | None:
    return value if _is_int(value) and value >= 0 else None


def _parse_iso_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed


def _valid_team(value: object) -> bool:
    return (
        isinstance(value, dict)
        and _is_int(value.get("id"))
        and isinstance(value.get("title"), str)
        and bool(value["title"].strip())
    )
