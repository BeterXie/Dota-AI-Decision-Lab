from dataclasses import dataclass
from datetime import datetime
from itertools import permutations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.draft import DraftSlot, DraftValidation
from app.models import HistoricalMapRecord, HistoricalPlayerMapRecord
from app.providers.dltv.draft_picks import DltvProviderPick
from app.providers.stratz.client import StratzClient
from app.providers.stratz.role_queries import (
    CURRENT_MATCH_ROLES_QUERY,
    ROLE_QUERY_VERSION,
    normalize_current_match_roles,
)
from app.repositories.raw import RawEventRepository

HISTORICAL_POSITION_RESOLVER_VERSION = "historical-dota-position-v1"
MAX_HISTORY_MAPS_PER_PLAYER = 40
# Four distinct pro maps are enough to establish a stable position share when
# the other guards still hold (>=35% share, >=20pp margin over the runner-up,
# and a full one-to-one assignment). Five maps previously blocked otherwise
# resolvable live drafts (for example one roster member with 4 tracked maps).
MIN_HISTORY_MAPS_PER_PLAYER = 4
MIN_ASSIGNED_POSITION_SHARE = 0.35
MIN_ASSIGNMENT_MARGIN = 0.20


@dataclass(frozen=True)
class DraftRoleResolution:
    draft: DraftValidation
    evidence_cutoff: datetime


class DraftRoleAssignmentService:
    def __init__(
        self,
        *,
        stratz: StratzClient | None,
        raw_events: RawEventRepository,
    ) -> None:
        self._stratz = stratz
        self._raw_events = raw_events

    async def resolve(
        self,
        session: AsyncSession,
        *,
        valve_match_id: int,
        picks: tuple[DltvProviderPick, ...],
        observed_at: datetime,
    ) -> DraftRoleResolution:
        blockers = _pick_blockers(picks)
        if blockers:
            return DraftRoleResolution(
                draft=DraftValidation(
                    complete=False,
                    slots=(),
                    blockers=blockers,
                    warnings=("DLTV_TEAM_SLOT_NOT_DOTA_POSITION",),
                ),
                evidence_cutoff=observed_at,
            )

        current = await self._resolve_current_match(
            session,
            valve_match_id=valve_match_id,
            picks=picks,
        )
        if current is not None:
            return current

        historical = await self._resolve_historical(
            session,
            picks=picks,
            observed_at=observed_at,
        )
        if historical is not None:
            return historical

        return DraftRoleResolution(
            draft=DraftValidation(
                complete=False,
                slots=(),
                blockers=("DRAFT_POSITION_UNRESOLVED",),
                warnings=(
                    "DLTV_TEAM_SLOT_NOT_DOTA_POSITION",
                    "POSITION_EVIDENCE_UNAVAILABLE_OR_AMBIGUOUS",
                ),
            ),
            evidence_cutoff=observed_at,
        )

    async def _resolve_current_match(
        self,
        session: AsyncSession,
        *,
        valve_match_id: int,
        picks: tuple[DltvProviderPick, ...],
    ) -> DraftRoleResolution | None:
        if self._stratz is None:
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
        draft = validate_role_assignment(slots)
        if not draft.complete:
            return None
        return DraftRoleResolution(draft=draft, evidence_cutoff=response.received_at)

    async def _resolve_historical(
        self,
        session: AsyncSession,
        *,
        picks: tuple[DltvProviderPick, ...],
        observed_at: datetime,
    ) -> DraftRoleResolution | None:
        account_ids = [pick.account_id for pick in picks if pick.account_id is not None]
        if len(account_ids) != 10 or len(set(account_ids)) != 10:
            return None

        rows = (
            await session.execute(
                select(
                    HistoricalPlayerMapRecord.account_id,
                    HistoricalPlayerMapRecord.position,
                    HistoricalPlayerMapRecord.basic_first_usable_at,
                    HistoricalMapRecord.provider_match_id,
                    HistoricalMapRecord.provider,
                    HistoricalMapRecord.started_at,
                )
                .join(
                    HistoricalMapRecord,
                    HistoricalMapRecord.id == HistoricalPlayerMapRecord.historical_map_id,
                )
                .where(
                    HistoricalPlayerMapRecord.account_id.in_(account_ids),
                    HistoricalPlayerMapRecord.position.in_((1, 2, 3, 4, 5)),
                    HistoricalPlayerMapRecord.basic_first_usable_at <= observed_at,
                    HistoricalMapRecord.first_usable_at <= observed_at,
                    HistoricalMapRecord.sync_status != "DATA_CONFLICT",
                )
                .order_by(
                    HistoricalMapRecord.started_at.desc(),
                    HistoricalMapRecord.provider.desc(),
                )
            )
        ).all()

        evidence: dict[int, list[tuple[int, datetime]]] = {
            account_id: [] for account_id in account_ids
        }
        seen_matches: dict[int, set[str]] = {account_id: set() for account_id in account_ids}
        for account_id, position, usable_at, provider_match_id, _provider, _started_at in rows:
            if account_id not in evidence or position not in (1, 2, 3, 4, 5):
                continue
            match_key = str(provider_match_id)
            if match_key in seen_matches[account_id]:
                continue
            if len(evidence[account_id]) >= MAX_HISTORY_MAPS_PER_PLAYER:
                continue
            seen_matches[account_id].add(match_key)
            evidence[account_id].append((position, usable_at))

        resolved_slots: list[DraftSlot] = []
        side_cutoffs: list[datetime] = []
        for side in ("radiant", "dire"):
            side_picks = tuple(pick for pick in picks if pick.side == side)
            resolved = _resolve_side_from_history(side_picks, evidence)
            if resolved is None:
                return None
            slots, cutoff = resolved
            resolved_slots.extend(slots)
            side_cutoffs.append(cutoff)

        draft = validate_role_assignment(resolved_slots)
        if not draft.complete:
            return None
        return DraftRoleResolution(
            draft=draft.model_copy(
                update={
                    "warnings": (
                        "DLTV_TEAM_SLOT_NOT_DOTA_POSITION",
                        "DRAFT_POSITION_INFERRED_FROM_HISTORICAL_PRO_MATCHES",
                        HISTORICAL_POSITION_RESOLVER_VERSION,
                    )
                }
            ),
            evidence_cutoff=max(side_cutoffs, default=observed_at),
        )


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


def _resolve_side_from_history(
    picks: tuple[DltvProviderPick, ...],
    evidence: dict[int, list[tuple[int, datetime]]],
) -> tuple[list[DraftSlot], datetime] | None:
    if len(picks) != 5 or any(pick.account_id is None or pick.hero_id is None for pick in picks):
        return None

    position_shares: dict[int, dict[int, float]] = {}
    sample_sizes: dict[int, int] = {}
    cutoffs: list[datetime] = []
    for pick in picks:
        account_id = pick.account_id
        if account_id is None:
            return None
        rows = evidence.get(account_id, [])
        if len(rows) < MIN_HISTORY_MAPS_PER_PLAYER:
            return None
        weighted: dict[int, float] = {position: 0.0 for position in range(1, 6)}
        for index, (position, usable_at) in enumerate(rows):
            weight = 1.0 if index < 5 else 0.70 if index < 15 else 0.40
            weighted[position] += weight
            cutoffs.append(usable_at)
        total = sum(weighted.values())
        if total <= 0:
            return None
        position_shares[account_id] = {
            position: value / total for position, value in weighted.items()
        }
        sample_sizes[account_id] = len(rows)

    ranked: list[tuple[float, tuple[int, ...]]] = []
    for assignment in permutations(range(1, 6)):
        score = 0.0
        valid = True
        for pick, position in zip(picks, assignment, strict=True):
            account_id = pick.account_id
            if account_id is None:
                return None
            share = position_shares[account_id][position]
            if share < MIN_ASSIGNED_POSITION_SHARE:
                valid = False
                break
            score += share
        if valid:
            ranked.append((score, assignment))
    if not ranked:
        return None
    ranked.sort(key=lambda item: item[0], reverse=True)
    best_score, best_assignment = ranked[0]
    second_score = ranked[1][0] if len(ranked) > 1 else 0.0
    margin = best_score - second_score
    if len(ranked) > 1 and margin < MIN_ASSIGNMENT_MARGIN:
        return None

    slots: list[DraftSlot] = []
    for pick, position in zip(picks, best_assignment, strict=True):
        account_id = pick.account_id
        hero_id = pick.hero_id
        if account_id is None or hero_id is None:
            return None
        share = position_shares[account_id][position]
        sample = sample_sizes[account_id]
        confidence = min(
            0.95,
            0.55 + (0.25 * share) + (0.10 * min(sample / 20.0, 1.0)) + (0.05 * min(margin, 1.0)),
        )
        slots.append(
            DraftSlot(
                side=pick.side,
                position=position,
                account_id=account_id,
                hero_id=hero_id,
                source="HISTORICAL_ROLE_ASSIGNMENT",
                confidence=confidence,
            )
        )
    return slots, max(cutoffs)


def _pick_blockers(picks: tuple[DltvProviderPick, ...]) -> tuple[str, ...]:
    blockers: list[str] = []
    if len(picks) != 10:
        blockers.append("DRAFT_PARTIAL")
        return tuple(blockers)
    heroes = [pick.hero_id for pick in picks if pick.hero_id is not None]
    if len(heroes) != 10:
        blockers.append("DRAFT_PARTIAL")
    elif len(heroes) != len(set(heroes)):
        blockers.append("DRAFT_HERO_DUPLICATE")
    account_ids = [pick.account_id for pick in picks if pick.account_id is not None]
    if len(account_ids) != 10 or len(set(account_ids)) != 10:
        blockers.append("ROSTER_IDENTITY_PARTIAL")
    for side in ("radiant", "dire"):
        side_picks = [pick for pick in picks if pick.side == side]
        if len(side_picks) != 5:
            blockers.append("DRAFT_PARTIAL")
            continue
        if {pick.provider_slot for pick in side_picks} != set(range(1, 6)):
            blockers.append("DRAFT_PROVIDER_SLOT_INVALID")
    return tuple(dict.fromkeys(blockers))
