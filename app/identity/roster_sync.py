from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.identity.roster_models import TeamRosterMembership
from app.models import CanonicalPlayer, CanonicalTeam, ProviderTeamMapping
from app.providers.common import TimedPayload
from app.repositories.raw import RawEventRepository


class TeamRosterClient(Protocol):
    normalizer_version: str

    async def get_team_players(self, team_id: str | int) -> TimedPayload: ...


@dataclass(frozen=True, slots=True)
class RosterSyncResult:
    team_id: UUID
    source_team_id: int | None
    current_players: int
    created_players: int
    created_memberships: int
    closed_memberships: int
    skipped: bool = False


class TeamRosterSyncService:
    def __init__(self, raw_events: RawEventRepository) -> None:
        self._raw_events = raw_events

    async def sync_team(
        self,
        session: AsyncSession,
        client: TeamRosterClient,
        *,
        canonical_team_id: UUID,
    ) -> RosterSyncResult:
        team = await session.get(CanonicalTeam, canonical_team_id)
        if team is None:
            return RosterSyncResult(canonical_team_id, None, 0, 0, 0, 0, skipped=True)
        mapping = await session.scalar(
            select(ProviderTeamMapping).where(
                ProviderTeamMapping.provider == "opendota",
                ProviderTeamMapping.canonical_team_id == canonical_team_id,
            )
        )
        if mapping is None:
            return RosterSyncResult(canonical_team_id, None, 0, 0, 0, 0, skipped=True)
        try:
            source_team_id = int(mapping.provider_team_id)
        except ValueError:
            return RosterSyncResult(canonical_team_id, None, 0, 0, 0, 0, skipped=True)

        response = await client.get_team_players(source_team_id)
        payload = response.payload
        if not isinstance(payload, list):
            return RosterSyncResult(canonical_team_id, source_team_id, 0, 0, 0, 0, skipped=True)
        raw_players = [item for item in payload if isinstance(item, dict)]
        current_players = [
            item for item in raw_players if item.get("is_current_team_member") is True
        ]
        await self._raw_events.append(
            session,
            provider="opendota",
            event_type="OPENDOTA_TEAM_ROSTER",
            provider_key=str(source_team_id),
            payload={"players": raw_players},
            request_started_at=response.request_started_at,
            received_at=response.received_at,
            parser_version=client.normalizer_version,
        )
        # Empty or partially unidentified rosters are discovery gaps, not proof
        # that known players left the team. We may add valid incoming players,
        # but only close stale memberships when every current row has a usable
        # Dota account id.
        if not current_players:
            return RosterSyncResult(canonical_team_id, source_team_id, 0, 0, 0, 0, skipped=True)
        valid_current_players = [
            item
            for item in current_players
            if isinstance(item.get("account_id"), int)
            and not isinstance(item.get("account_id"), bool)
        ]
        if not valid_current_players:
            return RosterSyncResult(canonical_team_id, source_team_id, 0, 0, 0, 0, skipped=True)
        roster_identity_complete = len(valid_current_players) == len(current_players)

        active = list(
            (
                await session.scalars(
                    select(TeamRosterMembership).where(
                        TeamRosterMembership.team_id == canonical_team_id,
                        TeamRosterMembership.role == "PLAYER",
                        TeamRosterMembership.valid_to.is_(None),
                    )
                )
            ).all()
        )
        active_by_player = {item.player_id: item for item in active if item.player_id is not None}
        incoming_player_ids: set[UUID] = set()
        created_players = created_memberships = 0

        for item in valid_current_players:
            account_id = item["account_id"]
            player = await session.scalar(
                select(CanonicalPlayer).where(CanonicalPlayer.account_id == account_id)
            )
            if player is None:
                source_name = item.get("name")
                player = CanonicalPlayer(
                    account_id=account_id,
                    name=(
                        source_name.strip()
                        if isinstance(source_name, str) and source_name.strip()
                        else None
                    ),
                )
                session.add(player)
                await session.flush()
                created_players += 1
            incoming_player_ids.add(player.id)
            membership = active_by_player.get(player.id)
            if membership is None:
                session.add(
                    TeamRosterMembership(
                        team_id=canonical_team_id,
                        player_id=player.id,
                        role="PLAYER",
                        valid_from=response.received_at,
                        source_name="opendota",
                        source_url=f"https://www.opendota.com/teams/{source_team_id}",
                        observed_at=response.received_at,
                        confidence=0.9,
                    )
                )
                created_memberships += 1
            elif membership.source_name == "opendota":
                membership.observed_at = response.received_at

        closed_memberships = 0
        if roster_identity_complete:
            for membership in active:
                if (
                    membership.source_name == "opendota"
                    and membership.player_id is not None
                    and membership.player_id not in incoming_player_ids
                ):
                    membership.valid_to = response.received_at
                    membership.observed_at = response.received_at
                    closed_memberships += 1

        return RosterSyncResult(
            canonical_team_id,
            source_team_id,
            len(incoming_player_ids),
            created_players,
            created_memberships,
            closed_memberships,
        )
