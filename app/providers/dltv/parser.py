from datetime import datetime
from typing import Any

from app.canonical import content_digest
from app.domain.draft import DraftSlot, DraftValidation
from app.domain.live import DltvFastPatch
from app.providers.dltv.models import DltvBootstrapIdentity, DltvSeries, DltvSeriesFrame

PARSER_VERSION = "dltv-v2"


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
        raw_hero_id = player.get("hero_id")
        team = player.get("team")
        position = player.get("team_slot")
        if team not in (0, 1) or not _is_int(position) or position not in range(1, 6):
            blockers.append("DRAFT_PARTIAL")
            continue
        hero_id = raw_hero_id if _is_int(raw_hero_id) and raw_hero_id > 0 else None
        if hero_id is None:
            blockers.append("DRAFT_PARTIAL")
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
    known_heroes = [slot.hero_id for slot in slots if slot.hero_id is not None]
    if len(known_heroes) != len(set(known_heroes)):
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


def parse_draft_labels(payload: dict[str, Any]) -> tuple[dict[int, str], dict[int, str]]:
    player_names: dict[int, str] = {}
    hero_names: dict[int, str] = {}
    live_league_data = payload.get("live_league_data")
    if isinstance(live_league_data, dict):
        raw_players = live_league_data.get("players")
        for item in raw_players if isinstance(raw_players, list) else []:
            if not isinstance(item, dict):
                continue
            account_id = _optional_int(item.get("account_id"))
            name = item.get("name")
            if account_id is not None and isinstance(name, str) and name.strip():
                player_names[account_id] = name.strip()

    full_stats = payload.get("full_stats")
    if isinstance(full_stats, dict):
        for side in ("radiant", "dire"):
            team = full_stats.get(side)
            if not isinstance(team, dict):
                continue
            raw_players = team.get("players")
            for item in raw_players if isinstance(raw_players, list) else []:
                if not isinstance(item, dict):
                    continue
                player = item.get("player")
                hero = item.get("hero")
                if isinstance(player, dict):
                    account_id = _optional_int(player.get("steam_id"))
                    name = player.get("title")
                    if account_id is not None and isinstance(name, str) and name.strip():
                        player_names[account_id] = name.strip()
                if isinstance(hero, dict):
                    hero_id = _optional_int(hero.get("steam_id"))
                    name = hero.get("title")
                    if (
                        hero_id is not None
                        and hero_id > 0
                        and isinstance(name, str)
                        and name.strip()
                    ):
                        hero_names[hero_id] = name.strip()
    return player_names, hero_names


def parse_fast_patch(
    payload: dict[str, Any],
    *,
    valve_match_id: int,
    received_at: datetime,
    connection_id: str | None = None,
    reconnect_generation: int = 0,
) -> DltvFastPatch:
    updates: dict[str, Any] = {}
    field_mapping = {
        "game_time": ("game_time_seconds", _optional_nonnegative_int),
        "radiant_score": ("radiant_kills", _optional_nonnegative_int),
        "dire_score": ("dire_kills", _optional_nonnegative_int),
        "radiant_lead": ("radiant_nw_lead", _optional_int),
    }
    for provider_field, (state_field, parser) in field_mapping.items():
        if provider_field in payload:
            raw_value = payload[provider_field]
            parsed_value = parser(raw_value)
            if raw_value is None or parsed_value is not None:
                updates[state_field] = parsed_value
    if "first_blood" in payload:
        value = payload["first_blood"]
        if value is None or isinstance(value, str):
            updates["first_blood"] = value
    game_time = updates.get("game_time_seconds")
    return DltvFastPatch(
        valve_match_id=valve_match_id,
        updates=updates,
        source_game_time=game_time if isinstance(game_time, int) else None,
        message_received_at=received_at,
        payload_hash=content_digest(payload),
        connection_id=connection_id,
        reconnect_generation=reconnect_generation,
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
