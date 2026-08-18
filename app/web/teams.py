from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.identity.roster_models import (
    CanonicalStaff,
    PlayerProfile,
    TeamProfile,
    TeamRosterMembership,
)
from app.models import CanonicalPlayer, CanonicalTeam, ProviderTeamMapping
from app.time import ensure_utc


def create_team_router(
    session_factory: async_sessionmaker[AsyncSession],
) -> APIRouter:
    router = APIRouter(prefix="/api/teams", tags=["teams"])

    @router.get("")
    async def team_directory() -> list[dict]:
        async with session_factory() as session:
            rows = (
                await session.execute(
                    select(CanonicalTeam, TeamProfile)
                    .outerjoin(TeamProfile, TeamProfile.canonical_team_id == CanonicalTeam.id)
                    .order_by(CanonicalTeam.name.asc())
                )
            ).all()
            opendota_ids = await _opendota_team_ids(session)
            return [
                _team_payload(team, profile, discovered_valve_team_id=opendota_ids.get(team.id))
                for team, profile in rows
            ]

    @router.get("/{team_id}")
    async def team_detail(team_id: UUID) -> dict:
        async with session_factory() as session:
            team = await session.get(CanonicalTeam, team_id)
            if team is None:
                raise HTTPException(status_code=404, detail="team not found")
            profile = await session.get(TeamProfile, team_id)
            discovered_valve_team_id = await _opendota_team_id(session, team_id)
            memberships = list(
                (
                    await session.scalars(
                        select(TeamRosterMembership)
                        .where(TeamRosterMembership.team_id == team_id)
                        .order_by(
                            TeamRosterMembership.valid_to.asc().nulls_first(),
                            TeamRosterMembership.position.asc().nulls_last(),
                            TeamRosterMembership.valid_from.desc().nulls_last(),
                        )
                    )
                ).all()
            )
            player_ids = [item.player_id for item in memberships if item.player_id is not None]
            staff_ids = [item.staff_id for item in memberships if item.staff_id is not None]
            players = (
                list(
                    (
                        await session.scalars(
                            select(CanonicalPlayer).where(CanonicalPlayer.id.in_(player_ids))
                        )
                    ).all()
                )
                if player_ids
                else []
            )
            player_profiles = (
                list(
                    (
                        await session.scalars(
                            select(PlayerProfile).where(
                                PlayerProfile.canonical_player_id.in_(player_ids)
                            )
                        )
                    ).all()
                )
                if player_ids
                else []
            )
            staff = (
                list(
                    (
                        await session.scalars(
                            select(CanonicalStaff).where(CanonicalStaff.id.in_(staff_ids))
                        )
                    ).all()
                )
                if staff_ids
                else []
            )
            player_by_id = {item.id: item for item in players}
            player_profile_by_id = {item.canonical_player_id: item for item in player_profiles}
            staff_by_id = {item.id: item for item in staff}
            roster = [
                _membership_payload(
                    item,
                    player=player_by_id.get(item.player_id) if item.player_id is not None else None,
                    player_profile=(
                        player_profile_by_id.get(item.player_id)
                        if item.player_id is not None
                        else None
                    ),
                    staff=staff_by_id.get(item.staff_id) if item.staff_id is not None else None,
                )
                for item in memberships
            ]
            return {
                **_team_payload(
                    team,
                    profile,
                    discovered_valve_team_id=discovered_valve_team_id,
                ),
                "current_roster": [item for item in roster if item["valid_to"] is None],
                "roster_history": roster,
            }

    @router.get("/by-slug/{slug}")
    async def team_detail_by_slug(slug: str) -> dict:
        async with session_factory() as session:
            team_id = await session.scalar(
                select(TeamProfile.canonical_team_id).where(TeamProfile.slug == slug)
            )
        if team_id is None:
            raise HTTPException(status_code=404, detail="team not found")
        return await team_detail(team_id)

    return router


async def _opendota_team_ids(session: AsyncSession) -> dict[UUID, int]:
    mappings = list(
        (
            await session.scalars(
                select(ProviderTeamMapping).where(ProviderTeamMapping.provider == "opendota")
            )
        ).all()
    )
    result: dict[UUID, int] = {}
    for mapping in mappings:
        try:
            team_id = int(mapping.provider_team_id)
        except ValueError:
            continue
        if team_id > 0:
            result[mapping.canonical_team_id] = team_id
    return result


async def _opendota_team_id(session: AsyncSession, team_id: UUID) -> int | None:
    mapping = await session.scalar(
        select(ProviderTeamMapping).where(
            ProviderTeamMapping.provider == "opendota",
            ProviderTeamMapping.canonical_team_id == team_id,
        )
    )
    if mapping is None:
        return None
    try:
        value = int(mapping.provider_team_id)
    except ValueError:
        return None
    return value if value > 0 else None


def _team_payload(
    team: CanonicalTeam,
    profile: TeamProfile | None,
    *,
    discovered_valve_team_id: int | None,
) -> dict:
    valve_team_id = (
        profile.valve_team_id if profile and profile.valve_team_id else discovered_valve_team_id
    )
    identity_source = (
        "registry" if profile and profile.valve_team_id else "opendota" if valve_team_id else None
    )
    return {
        "id": str(team.id),
        "name": team.name,
        "slug": profile.slug if profile else None,
        "short_name": profile.short_name if profile else None,
        "valve_team_id": valve_team_id,
        "identity_source": identity_source,
        "country_code": profile.country_code if profile else None,
        "logo_url": profile.logo_url if profile else None,
        "logo_source": (
            profile.logo_source
            if profile and profile.logo_source
            else "valve-steam"
            if valve_team_id
            else None
        ),
        "website_url": profile.website_url if profile else None,
        "source_url": (
            profile.source_url
            if profile and profile.source_url
            else f"https://www.opendota.com/teams/{valve_team_id}"
            if valve_team_id
            else None
        ),
        "observed_at": _utc(profile.observed_at) if profile else None,
    }


def _membership_payload(
    membership: TeamRosterMembership,
    *,
    player: CanonicalPlayer | None,
    player_profile: PlayerProfile | None,
    staff: CanonicalStaff | None,
) -> dict:
    if player is not None:
        subject = {
            "type": "PLAYER",
            "id": str(player.id),
            "name": player.name,
            "account_id": player.account_id,
            "real_name": player_profile.real_name if player_profile else None,
            "country_code": player_profile.country_code if player_profile else None,
            "avatar_url": player_profile.avatar_url if player_profile else None,
        }
    elif staff is not None:
        subject = {
            "type": "STAFF",
            "id": str(staff.id),
            "name": staff.name,
            "account_id": None,
            "real_name": staff.real_name,
            "country_code": staff.country_code,
            "avatar_url": staff.avatar_url,
        }
    else:
        subject = {
            "type": "UNKNOWN",
            "id": None,
            "name": None,
            "account_id": None,
            "real_name": None,
            "country_code": None,
            "avatar_url": None,
        }
    return {
        "id": str(membership.id),
        "subject": subject,
        "role": membership.role,
        "position": membership.position,
        "is_standin": membership.is_standin,
        "valid_from": _utc(membership.valid_from),
        "valid_to": _utc(membership.valid_to),
        "source_name": membership.source_name,
        "source_url": membership.source_url,
        "observed_at": _utc(membership.observed_at),
        "confidence": membership.confidence,
    }


def _utc(value: datetime | None) -> datetime | None:
    return ensure_utc(value) if value is not None else None