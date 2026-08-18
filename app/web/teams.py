from __future__ import annotations

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
from app.models import CanonicalPlayer, CanonicalTeam


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
            return [_team_payload(team, profile) for team, profile in rows]

    @router.get("/{team_id}")
    async def team_detail(team_id: UUID) -> dict:
        async with session_factory() as session:
            team = await session.get(CanonicalTeam, team_id)
            if team is None:
                raise HTTPException(status_code=404, detail="team not found")
            profile = await session.get(TeamProfile, team_id)
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
                **_team_payload(team, profile),
                "current_roster": [item for item in roster if item["valid_to"] is None],
                "roster_history": roster,
            }

    return router


def _team_payload(team: CanonicalTeam, profile: TeamProfile | None) -> dict:
    return {
        "id": str(team.id),
        "name": team.name,
        "slug": profile.slug if profile else None,
        "short_name": profile.short_name if profile else None,
        "valve_team_id": profile.valve_team_id if profile else None,
        "country_code": profile.country_code if profile else None,
        "logo_url": profile.logo_url if profile else None,
        "logo_source": profile.logo_source if profile else None,
        "website_url": profile.website_url if profile else None,
        "source_url": profile.source_url if profile else None,
        "observed_at": profile.observed_at if profile else None,
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
        "valid_from": membership.valid_from,
        "valid_to": membership.valid_to,
        "source_name": membership.source_name,
        "source_url": membership.source_url,
        "observed_at": membership.observed_at,
        "confidence": membership.confidence,
    }
