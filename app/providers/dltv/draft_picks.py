from dataclasses import dataclass
from typing import Any, Literal


@dataclass(frozen=True)
class DltvProviderPick:
    side: Literal["radiant", "dire"]
    provider_slot: int
    account_id: int | None
    hero_id: int | None


def parse_dltv_provider_picks(payload: dict[str, Any]) -> tuple[DltvProviderPick, ...]:
    players = payload.get("players")
    if not isinstance(players, list) or len(players) != 10:
        return ()
    picks: list[DltvProviderPick] = []
    for player in players:
        if not isinstance(player, dict):
            return ()
        team = player.get("team")
        provider_slot = player.get("team_slot")
        if team not in (0, 1) or not _is_int(provider_slot) or provider_slot not in range(1, 6):
            return ()
        account_id = player.get("account_id")
        hero_id = player.get("hero_id")
        picks.append(
            DltvProviderPick(
                side="radiant" if team == 0 else "dire",
                provider_slot=provider_slot,
                account_id=account_id if _is_int(account_id) else None,
                hero_id=hero_id if _is_int(hero_id) and hero_id > 0 else None,
            )
        )
    return tuple(picks)


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)
