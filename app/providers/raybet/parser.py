from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

from app.domain.identity import ProviderMatch
from app.domain.market import OddsDelta, OddsMeta

PARSER_VERSION = "raybet-v1"


def parse_matches(
    payload: dict[str, Any],
    *,
    observed_at: datetime,
    dota_game_id: int,
    naive_timezone: str,
) -> list[ProviderMatch]:
    result = payload.get("result")
    if not isinstance(result, list):
        return []
    matches: list[ProviderMatch] = []
    for item in result:
        if not isinstance(item, dict) or item.get("game_id") != dota_game_id:
            continue
        teams = item.get("team")
        if not isinstance(teams, list) or len(teams) != 2:
            continue
        team_a, team_b = sorted(teams, key=lambda team: team.get("pos", 99))
        if not _valid_team(team_a) or not _valid_team(team_b):
            continue
        provider_match_id = item.get("id")
        if not _is_int(provider_match_id):
            continue
        matches.append(
            ProviderMatch(
                provider_match_id=provider_match_id,
                game_id=dota_game_id,
                tournament_id=_optional_int(item.get("tournament_id")),
                tournament_name=_optional_string(item.get("tournament_name")),
                team_a_id=team_a["team_id"],
                team_a_name=team_a["team_name"],
                team_b_id=team_b["team_id"],
                team_b_name=team_b["team_name"],
                round=_optional_string(item.get("round")),
                provider_status=_optional_int(item.get("status")),
                scheduled_at=_parse_provider_datetime(item.get("start_time"), naive_timezone),
                observed_at=observed_at,
            )
        )
    return matches


def parse_odds_registry(payload: dict[str, Any]) -> list[OddsMeta]:
    result = payload.get("result")
    odds = result.get("odds") if isinstance(result, dict) else None
    if not isinstance(odds, list):
        return []
    metadata: list[OddsMeta] = []
    for item in odds:
        if not isinstance(item, dict):
            continue
        odds_id = item.get("odds_id", item.get("id"))
        match_id = item.get("match_id")
        if not _is_int(odds_id) or not _is_int(match_id):
            continue
        metadata.append(
            OddsMeta(
                odds_id=odds_id,
                match_id=match_id,
                team_id=_optional_int(item.get("team_id")),
                team_name=_optional_string(item.get("name")),
                group_short_name=_optional_string(item.get("group_short_name")),
                match_stage=_optional_string(item.get("match_stage")),
                raw_status=_optional_int(item.get("status")),
            )
        )
    return metadata


def parse_odds_bootstrap(payload: dict[str, Any]) -> list[OddsDelta]:
    result = payload.get("result")
    odds = result.get("odds") if isinstance(result, dict) else None
    if not isinstance(odds, list):
        return []
    deltas: list[OddsDelta] = []
    for item in odds:
        if not isinstance(item, dict):
            continue
        odds_id = item.get("odds_id", item.get("id"))
        match_id = item.get("match_id")
        if not _is_int(odds_id) or not _is_int(match_id):
            continue
        try:
            price = Decimal(str(item.get("odds")))
        except InvalidOperation, TypeError:
            continue
        if price <= 1:
            continue
        deltas.append(
            OddsDelta(
                odds_id=odds_id,
                match_id=match_id,
                price=price,
                raw_status=_optional_int(item.get("status")),
                provider_updated_at=_parse_epoch(item.get("last_update")),
            )
        )
    return deltas


def parse_socket_publish(message: str | dict[str, Any]) -> list[OddsDelta]:
    if isinstance(message, str):
        import json

        try:
            decoded = json.loads(message)
        except json.JSONDecodeError:
            return []
    else:
        decoded = message
    if decoded.get("event") != "#publish":
        return []
    envelope = decoded.get("data")
    if not isinstance(envelope, dict) or envelope.get("channel") != "match":
        return []
    data = envelope.get("data")
    if not isinstance(data, dict) or data.get("source") != "odds":
        return []
    raw_odds = data.get("odds")
    if not isinstance(raw_odds, list):
        return []
    deltas: list[OddsDelta] = []
    for item in raw_odds:
        if not isinstance(item, dict):
            continue
        odds_id = item.get("id")
        match_id = item.get("match_id")
        if not _is_int(odds_id) or not _is_int(match_id):
            continue
        try:
            price = Decimal(str(item.get("odds")))
        except InvalidOperation, TypeError:
            continue
        if price <= 1:
            continue
        deltas.append(
            OddsDelta(
                odds_id=odds_id,
                match_id=match_id,
                price=price,
                raw_status=_optional_int(item.get("status")),
                provider_updated_at=_parse_epoch(item.get("last_update")),
            )
        )
    return deltas


def _valid_team(value: object) -> bool:
    return (
        isinstance(value, dict)
        and _is_int(value.get("team_id"))
        and isinstance(value.get("team_name"), str)
        and bool(value["team_name"].strip())
    )


def _parse_provider_datetime(value: object, timezone_name: str) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    return parsed.replace(tzinfo=ZoneInfo(timezone_name)).astimezone(UTC)


def _parse_epoch(value: object) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(str(value)), tz=UTC)
    except TypeError, ValueError, OSError:
        return None


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _optional_int(value: object) -> int | None:
    return value if _is_int(value) else None


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None
