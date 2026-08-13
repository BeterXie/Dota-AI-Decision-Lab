from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class DltvProviderPick:
    side: Literal["radiant", "dire"]
    provider_slot: int
    account_id: int | None
    hero_id: int | None
