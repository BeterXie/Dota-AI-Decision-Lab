from typing import Any

ROLE_QUERY_VERSION = "stratz-current-match-roles-v1"

CURRENT_MATCH_ROLES_QUERY = """
query CurrentMatchRoles($matchId: Long!) {
  match(id: $matchId) {
    id
    players {
      steamAccountId
      heroId
      position
      isRadiant
    }
  }
}
"""


def normalize_current_match_roles(
    payload: dict[str, Any], *, match_id: int
) -> list[dict[str, Any]]:
    data = payload.get("data")
    match = data.get("match") if isinstance(data, dict) else None
    if not isinstance(match, dict) or match.get("id") != match_id:
        return []
    rows = match.get("players")
    if not isinstance(rows, list):
        return []

    normalized: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        account_id = _int(row.get("steamAccountId"))
        hero_id = _int(row.get("heroId"))
        position = parse_position(row.get("position"))
        is_radiant = row.get("isRadiant")
        if (
            account_id is None
            or hero_id is None
            or hero_id <= 0
            or position is None
            or not isinstance(is_radiant, bool)
        ):
            continue
        normalized.append(
            {
                "account_id": account_id,
                "hero_id": hero_id,
                "position": position,
                "side": "radiant" if is_radiant else "dire",
            }
        )
    return normalized


def parse_position(value: object) -> int | None:
    parsed = _int(value)
    if parsed in {1, 2, 3, 4, 5}:
        return parsed
    if not isinstance(value, str):
        return None
    normalized = value.strip().upper()
    if not normalized.startswith("POSITION_"):
        return None
    suffix = normalized.removeprefix("POSITION_")
    if not suffix.isdigit():
        return None
    parsed = int(suffix)
    return parsed if parsed in {1, 2, 3, 4, 5} else None


def _int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None
