from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.draft import DraftSlot, DraftValidation
from app.providers.stratz.client import StratzClient
from app.providers.stratz.role_queries import (
    CURRENT_MATCH_ROLES_QUERY,
    ROLE_QUERY_VERSION,
    normalize_current_match_roles,
)
from app.repositories.raw import RawEventRepository


@dataclass(frozen=True)
class DltvDraftPick:
    side: Literal["radiant", "dire"]
    provider_slot: int
    account_id: int | None
    hero_id: int | None


class DraftRoleAssignmentService:
    def __init__(
        self,
        *,
        stratz: StratzClient | None,
        raw_events: RawEventRepository,
    ) -> None:
        self._stratz = stratz
        self._raw_events = raw_events

    async def resolve_current_match(
        self,
        session: AsyncSession,
        *,
        valve_match_id: int,
        picks: tuple[DltvDraftPick, ...],
        observed_at: datetime,
    ) -> DraftValidation | None:
        if self._stratz is None or _pick_blockers(picks):
            return None
        try:
            response = await self._stratz.execute(
                operation_name="CurrentMatchRoles",
                query=CURRENT_MATCH_ROLES_QUERY,
                variables={"matchId": valve_match_id},
            )
        except Exception:
            return None
        await self._raw_events.append(
            session,
            provider="stratz",
            event_type="STRATZ_CURRENT_MATCH_ROLES",
            provider_key=str(valve_match_id),
            payload={
                "request": {
                    "operation_name": "CurrentMatchRoles",
                    "variables": {"matchId": valve_match_id},
                    "query_version": ROLE_QUERY_VERSION,
                },
                "response": response.payload,
            },
            request_started_at=response.request_started_at,
            received_at=response.received_at,
            parser_version=ROLE_QUERY_VERSION,
        )
        rows = normalize_current_match_roles(response.payload, match_id=valve_match_id)
        by_identity = {
            (row["side"], row["account_id"], row["hero_id"]): row["position"] for row in rows
        }
        slots: list[DraftSlot] = []
        for pick in picks:
            if pick.account_id is None or pick.hero_id is None:
                return None
            position = by_identity.get((pick.side, pick.account_id, pick.hero_id))
            if position is None:
                return None
            slots.append(
                DraftSlot(
                    side=pick.side,
                    position=position,
                    account_id=pick.account_id,
                    hero_id=pick.hero_id,
                    source="STRATZ_CURRENT_MATCH",
                    confidence=1.0,
                )
            )
        return validate_role_assignment(slots)


def validate_role_assignment(slots: list[DraftSlot]) -> DraftValidation:
    blockers: list[str] = []
    if len(slots) != 10:
        blockers.append("DRAFT_POSITION_UNRESOLVED")
    for side in ("radiant", "dire"):
        side_slots = [slot for slot in slots if slot.side == side]
        if len(side_slots) != 5 or {slot.position for slot in side_slots} != set(range(1, 6)):
            blockers.append("DRAFT_POSITION_UNRESOLVED")
    return DraftValidation(
        complete=not blockers,
        slots=tuple(sorted(slots, key=lambda slot: (slot.side, slot.position))),
        blockers=tuple(dict.fromkeys(blockers)),
    )


def _pick_blockers(picks: tuple[DltvDraftPick, ...]) -> tuple[str, ...]:
    blockers: list[str] = []
    if len(picks) != 10 or any(pick.hero_id is None for pick in picks):
        blockers.append("DRAFT_PARTIAL")
    heroes = [pick.hero_id for pick in picks if pick.hero_id is not None]
    if len(heroes) != len(set(heroes)):
        blockers.append("DRAFT_HERO_DUPLICATE")
    for side in ("radiant", "dire"):
        side_picks = [pick for pick in picks if pick.side == side]
        if len(side_picks) != 5:
            blockers.append("DRAFT_PARTIAL")
        if {pick.provider_slot for pick in side_picks} != set(range(1, 6)):
            blockers.append("DRAFT_PROVIDER_SLOT_INVALID")
    return tuple(dict.fromkeys(blockers))
