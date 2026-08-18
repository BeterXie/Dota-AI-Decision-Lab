from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.identity.roster_models import TeamProfile
from app.identity.roster_sync import RosterSyncResult, TeamRosterSyncService
from app.models import CanonicalTeam, ProviderTeamMapping
from app.providers.common import TimedPayload
from app.repositories.raw import RawEventRepository


class TeamRegistryClient(Protocol):
    normalizer_version: str

    async def get_team_catalog(self, page: int = 0) -> TimedPayload: ...

    async def get_team_players(self, team_id: str | int) -> TimedPayload: ...


@dataclass(frozen=True, slots=True)
class TeamPopulationResult:
    team_id: UUID
    valve_team_id: int | None
    slug: str | None
    profile_created: bool
    roster: RosterSyncResult | None
    skipped: bool = False


class TeamRegistryPopulationService:
    """Populate maintained team profiles and current player rosters from known identities.

    Provider data is discovery input, not an authoritative overwrite. Existing
    maintained profile fields are preserved; only missing identity/presentation
    fields are filled automatically.
    """

    def __init__(self, raw_events: RawEventRepository) -> None:
        self._raw_events = raw_events
        self._rosters = TeamRosterSyncService(raw_events)

    async def populate(
        self,
        session: AsyncSession,
        client: TeamRegistryClient,
        *,
        canonical_team_ids: list[UUID] | None = None,
    ) -> list[TeamPopulationResult]:
        query = select(ProviderTeamMapping).where(ProviderTeamMapping.provider == "opendota")
        if canonical_team_ids:
            query = query.where(ProviderTeamMapping.canonical_team_id.in_(canonical_team_ids))
        mappings = list((await session.scalars(query)).all())
        if not mappings:
            return []

        response = await client.get_team_catalog(0)
        payload = response.payload
        await self._raw_events.append(
            session,
            provider="opendota",
            event_type="OPENDOTA_TEAM_REGISTRY_CATALOG",
            provider_key="0",
            payload={"teams": payload} if isinstance(payload, list) else payload,
            request_started_at=response.request_started_at,
            received_at=response.received_at,
            parser_version=client.normalizer_version,
        )
        catalog = (
            {
                item["team_id"]: item
                for item in payload
                if isinstance(item, dict) and isinstance(item.get("team_id"), int)
            }
            if isinstance(payload, list)
            else {}
        )
        used_slugs = {
            value
            for value in (
                await session.scalars(select(TeamProfile.slug).where(TeamProfile.slug.is_not(None)))
            ).all()
            if value
        }

        results: list[TeamPopulationResult] = []
        for mapping in mappings:
            try:
                valve_team_id = int(mapping.provider_team_id)
            except ValueError:
                results.append(
                    TeamPopulationResult(
                        mapping.canonical_team_id,
                        None,
                        None,
                        False,
                        None,
                        skipped=True,
                    )
                )
                continue
            if valve_team_id <= 0:
                results.append(
                    TeamPopulationResult(
                        mapping.canonical_team_id,
                        None,
                        None,
                        False,
                        None,
                        skipped=True,
                    )
                )
                continue

            team = await session.get(CanonicalTeam, mapping.canonical_team_id)
            if team is None:
                results.append(
                    TeamPopulationResult(
                        mapping.canonical_team_id,
                        valve_team_id,
                        None,
                        False,
                        None,
                        skipped=True,
                    )
                )
                continue

            item = catalog.get(valve_team_id, {})
            profile = await session.get(TeamProfile, team.id)
            if (
                profile is not None
                and profile.valve_team_id is not None
                and profile.valve_team_id != valve_team_id
            ):
                # A maintained Valve identity disagreeing with the provider mapping
                # is an identity conflict. Do not attach provider roster data to the
                # team until the mapping/profile conflict is reviewed explicitly.
                results.append(
                    TeamPopulationResult(
                        team.id,
                        profile.valve_team_id,
                        profile.slug,
                        False,
                        None,
                        skipped=True,
                    )
                )
                continue

            profile_created = profile is None
            if profile is None:
                profile = TeamProfile(canonical_team_id=team.id)
                session.add(profile)

            source_name = item.get("name") if isinstance(item.get("name"), str) else None
            if profile.slug is None:
                base = _slugify(source_name or team.name) or f"team-{valve_team_id}"
                profile.slug = _unique_slug(base, used_slugs)
                used_slugs.add(profile.slug)
            if profile.short_name is None:
                tag = item.get("tag")
                if isinstance(tag, str) and tag.strip():
                    profile.short_name = tag.strip()[:64]
            if profile.valve_team_id is None:
                profile.valve_team_id = valve_team_id
            if profile.logo_url is None:
                profile.logo_url = _valve_logo_url(valve_team_id)
                profile.logo_source = profile.logo_source or "valve-steam"
            if profile.source_url is None:
                profile.source_url = f"https://www.opendota.com/teams/{valve_team_id}"
            if profile.observed_at is None or _is_opendota_source(profile.source_url):
                profile.observed_at = response.received_at

            roster = await self._rosters.sync_team(
                session,
                client,
                canonical_team_id=team.id,
            )
            results.append(
                TeamPopulationResult(
                    team.id,
                    valve_team_id,
                    profile.slug,
                    profile_created,
                    roster,
                )
            )

        return results


def _slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")[:150]


def _unique_slug(base: str, used: set[str]) -> str:
    if base not in used:
        return base
    suffix = 2
    while f"{base}-{suffix}" in used:
        suffix += 1
    return f"{base}-{suffix}"


def _valve_logo_url(team_id: int) -> str:
    return f"https://steamcdn-a.akamaihd.net/apps/dota2/images/team_logos/{team_id}.png"


def _is_opendota_source(value: str | None) -> bool:
    return bool(value and value.startswith("https://www.opendota.com/teams/"))
