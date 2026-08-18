from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.identity.roster_models import TeamProfile, TeamRosterMembership
from app.models import CanonicalPlayer, CanonicalTeam, TeamAlias, utc_now

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def normalize_team_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return _NON_ALNUM.sub("", normalized.casefold())


def build_team_discovery_index(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        team_id = row.get("team_id")
        if not isinstance(team_id, int) or isinstance(team_id, bool):
            continue
        for key in ("name", "tag"):
            value = row.get(key)
            if isinstance(value, str) and value.strip():
                normalized = normalize_team_name(value)
                if normalized:
                    index[normalized].append(row)
    return dict(index)


def unique_team_candidate(
    names: list[str], index: dict[str, list[dict[str, Any]]]
) -> dict[str, Any] | None:
    candidates: dict[int, dict[str, Any]] = {}
    for name in names:
        for row in index.get(normalize_team_name(name), []):
            team_id = row.get("team_id")
            if isinstance(team_id, int) and not isinstance(team_id, bool):
                candidates[team_id] = row
    return next(iter(candidates.values())) if len(candidates) == 1 else None


async def sync_discovered_teams(
    session: AsyncSession,
    source_teams: list[dict[str, Any]],
    *,
    observed_at: datetime | None = None,
) -> dict[str, int]:
    observed = observed_at or utc_now()
    canonical_teams = list((await session.scalars(select(CanonicalTeam))).all())
    aliases = list((await session.scalars(select(TeamAlias))).all())
    aliases_by_team: dict[Any, list[str]] = defaultdict(list)
    for alias in aliases:
        aliases_by_team[alias.canonical_team_id].append(alias.name)
    index = build_team_discovery_index(source_teams)
    matched = updated = ambiguous = 0

    for team in canonical_teams:
        candidate = unique_team_candidate([team.name, *aliases_by_team.get(team.id, [])], index)
        if candidate is None:
            normalized_names = {
                normalize_team_name(name)
                for name in [team.name, *aliases_by_team.get(team.id, [])]
                if name
            }
            if any(len(index.get(name, [])) > 1 for name in normalized_names):
                ambiguous += 1
            continue
        matched += 1
        source_team_id = candidate["team_id"]
        profile = await session.get(TeamProfile, team.id)
        if profile is None:
            profile = TeamProfile(canonical_team_id=team.id)
            session.add(profile)
        changed = False
        if profile.valve_team_id != source_team_id:
            profile.valve_team_id = source_team_id
            changed = True
        tag = candidate.get("tag")
        if isinstance(tag, str) and tag.strip() and profile.short_name != tag.strip():
            profile.short_name = tag.strip()
            changed = True
        profile.logo_source = "valve-steam"
        profile.source_url = f"https://www.opendota.com/teams/{source_team_id}"
        profile.observed_at = observed
        profile.updated_at = observed
        if changed:
            updated += 1

    return {"matched": matched, "updated": updated, "ambiguous": ambiguous}


async def sync_discovered_roster(
    session: AsyncSession,
    team: CanonicalTeam,
    source_team_id: int,
    source_players: list[dict[str, Any]],
    *,
    observed_at: datetime | None = None,
) -> dict[str, int]:
    observed = observed_at or utc_now()
    incoming_player_ids: set[Any] = set()
    created_players = created_memberships = closed_memberships = 0

    for row in source_players:
        if row.get("is_current_team_member") is not True:
            continue
        account_id = row.get("account_id")
        if not isinstance(account_id, int) or isinstance(account_id, bool):
            continue
        player = await session.scalar(
            select(CanonicalPlayer).where(CanonicalPlayer.account_id == account_id)
        )
        if player is None:
            name = row.get("name")
            player = CanonicalPlayer(
                account_id=account_id,
                name=name.strip() if isinstance(name, str) and name.strip() else None,
            )
            session.add(player)
            await session.flush()
            created_players += 1
        incoming_player_ids.add(player.id)
        active = await session.scalar(
            select(TeamRosterMembership).where(
                TeamRosterMembership.team_id == team.id,
                TeamRosterMembership.player_id == player.id,
                TeamRosterMembership.valid_to.is_(None),
            )
        )
        if active is None:
            session.add(
                TeamRosterMembership(
                    team_id=team.id,
                    player_id=player.id,
                    role="PLAYER",
                    valid_from=observed,
                    source_name="opendota-discovery",
                    source_url=f"https://www.opendota.com/teams/{source_team_id}",
                    observed_at=observed,
                    confidence=0.9,
                )
            )
            created_memberships += 1

    active_discovered = list(
        (
            await session.scalars(
                select(TeamRosterMembership).where(
                    TeamRosterMembership.team_id == team.id,
                    TeamRosterMembership.role == "PLAYER",
                    TeamRosterMembership.source_name == "opendota-discovery",
                    TeamRosterMembership.valid_to.is_(None),
                )
            )
        ).all()
    )
    for membership in active_discovered:
        if membership.player_id not in incoming_player_ids:
            membership.valid_to = observed
            membership.observed_at = observed
            closed_memberships += 1

    return {
        "created_players": created_players,
        "created_memberships": created_memberships,
        "closed_memberships": closed_memberships,
    }
