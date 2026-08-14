from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.identity.aliases import equivalent_team_aliases, normalize_alias
from app.models import (
    CanonicalSeries,
    CanonicalTeam,
    HistoricalMapRecord,
    HistoricalPlayerMapRecord,
    MapResultEvidenceRecord,
    MapResultRecord,
    OddsObservationRecord,
    ProviderTeamMapping,
    TeamAlias,
    TeamFormSnapshotRecord,
    TeamRatingSnapshotRecord,
)
from app.providers.opendota.client import OpenDotaClient
from app.repositories.raw import RawEventRepository


class HistoricalTeamResolver:
    def __init__(self, raw_events: RawEventRepository) -> None:
        self._raw_events = raw_events
        self._opendota_catalog: list[dict] | None = None

    async def refresh_opendota_catalog(
        self,
        session: AsyncSession,
        client: OpenDotaClient,
        *,
        canonical_team_ids: list[UUID],
        max_pages: int = 20,
    ) -> int:
        names: dict[str, set[UUID]] = {}
        for team_id in canonical_team_ids:
            team = await session.get(CanonicalTeam, team_id)
            if team is not None:
                for alias in equivalent_team_aliases(team.name):
                    names.setdefault(alias, set()).add(team.id)
            aliases = list(
                (
                    await session.scalars(
                        select(TeamAlias).where(TeamAlias.canonical_team_id == team_id)
                    )
                ).all()
            )
            for alias in aliases:
                for equivalent in equivalent_team_aliases(alias.normalized_name):
                    names.setdefault(equivalent, set()).add(team_id)

        unresolved = set(canonical_team_ids)
        existing_ids = set(
            (
                await session.scalars(
                    select(ProviderTeamMapping.canonical_team_id).where(
                        ProviderTeamMapping.provider == "opendota",
                        ProviderTeamMapping.canonical_team_id.in_(unresolved),
                    )
                )
            ).all()
        )
        unresolved -= existing_ids
        if not unresolved:
            return 0
        resolved = 0
        if self._opendota_catalog is None:
            response = await client.get_team_catalog(0)
            payload = response.payload
            await self._raw_events.append(
                session,
                provider="opendota",
                event_type="OPENDOTA_TEAM_CATALOG",
                provider_key="0",
                payload={"teams": payload} if isinstance(payload, list) else payload,
                request_started_at=response.request_started_at,
                received_at=response.received_at,
                parser_version=client.normalizer_version,
            )
            if not isinstance(payload, list):
                return 0
            self._opendota_catalog = [item for item in payload if isinstance(item, dict)]
        resolved = await self._match_opendota_catalog(names, unresolved, session)
        if unresolved:
            # The in-process catalog may have been fetched before a newly
            # discovered tournament team appeared in OpenDota. Refresh once
            # when an unresolved identity remains instead of keeping stale
            # process-local coverage forever.
            response = await client.get_team_catalog(0)
            payload = response.payload
            await self._raw_events.append(
                session,
                provider="opendota",
                event_type="OPENDOTA_TEAM_CATALOG_REFRESH",
                provider_key="0",
                payload={"teams": payload} if isinstance(payload, list) else payload,
                request_started_at=response.request_started_at,
                received_at=response.received_at,
                parser_version=client.normalizer_version,
            )
            if isinstance(payload, list):
                self._opendota_catalog = [item for item in payload if isinstance(item, dict)]
                resolved += await self._match_opendota_catalog(names, unresolved, session)
        return resolved

    async def _match_opendota_catalog(
        self,
        names: dict[str, set[UUID]],
        unresolved: set[UUID],
        session: AsyncSession,
    ) -> int:
        resolved = 0
        for item in self._opendota_catalog or []:
            provider_id = item.get("team_id")
            name = item.get("name")
            if not isinstance(provider_id, int) or not isinstance(name, str):
                continue
            candidates = names.get(normalize_alias(name), set()) & unresolved
            if len(candidates) != 1:
                continue
            canonical_team_id = next(iter(candidates))
            existing = await session.scalar(
                select(ProviderTeamMapping).where(
                    ProviderTeamMapping.provider == "opendota",
                    ProviderTeamMapping.provider_team_id == str(provider_id),
                )
            )
            if existing is None:
                session.add(
                    ProviderTeamMapping(
                        provider="opendota",
                        provider_team_id=str(provider_id),
                        canonical_team_id=canonical_team_id,
                        observed_name=name,
                    )
                )
            elif existing.canonical_team_id != canonical_team_id:
                placeholder = await session.get(CanonicalTeam, existing.canonical_team_id)
                if placeholder is None or placeholder.name != f"OPENDOTA team {provider_id}":
                    continue
                await _merge_placeholder_team(
                    session,
                    source_team_id=placeholder.id,
                    target_team_id=canonical_team_id,
                )
                existing.canonical_team_id = canonical_team_id
                existing.observed_name = name
                await session.delete(placeholder)
            unresolved.remove(canonical_team_id)
            resolved += 1
        return resolved

    async def refresh_stratz_identities(
        self,
        session: AsyncSession,
        provider: object,
        *,
        canonical_team_ids: list[UUID],
    ) -> int:
        unresolved = set(canonical_team_ids)
        if not unresolved or not hasattr(provider, "get_team_identities"):
            return 0
        mappings = list(
            (
                await session.scalars(
                    select(ProviderTeamMapping).where(
                        ProviderTeamMapping.provider == "opendota",
                        ProviderTeamMapping.canonical_team_id.in_(unresolved),
                    )
                )
            ).all()
        )
        provider_ids = [int(item.provider_team_id) for item in mappings]
        if not provider_ids:
            return 0
        response = await provider.get_team_identities(provider_ids)
        payload = response.payload
        raw_identities = payload.get("data", {}).get("teams") if isinstance(payload, dict) else None
        if not isinstance(raw_identities, list):
            return 0
        await self._raw_events.append(
            session,
            provider="stratz",
            event_type="STRATZ_TEAM_IDENTITIES",
            provider_key=",".join(str(item) for item in provider_ids),
            payload=payload,
            request_started_at=response.request_started_at,
            received_at=response.received_at,
            parser_version=provider.normalizer_version,
        )
        names_by_id = {
            str(item.get("id")): item.get("name")
            for item in raw_identities
            if isinstance(item, dict) and isinstance(item.get("id"), int)
        }
        resolved = 0
        for mapping in mappings:
            name = names_by_id.get(mapping.provider_team_id)
            if not isinstance(name, str):
                continue
            team = await session.get(CanonicalTeam, mapping.canonical_team_id)
            if team is None or not _names_match(team.name, name):
                continue
            existing = await session.scalar(
                select(ProviderTeamMapping).where(
                    ProviderTeamMapping.provider == "stratz",
                    ProviderTeamMapping.provider_team_id == mapping.provider_team_id,
                )
            )
            if existing is None:
                session.add(
                    ProviderTeamMapping(
                        provider="stratz",
                        provider_team_id=mapping.provider_team_id,
                        canonical_team_id=mapping.canonical_team_id,
                        observed_name=name,
                    )
                )
                resolved += 1
        return resolved

    async def resolve_observed_match_teams(
        self,
        session: AsyncSession,
        *,
        provider: str,
        observed_teams: tuple[tuple[str, str | None], ...],
        expected_team_ids: set[UUID],
    ) -> int:
        resolved = 0
        expected_teams = {
            team_id: await session.get(CanonicalTeam, team_id) for team_id in expected_team_ids
        }
        for provider_team_id, observed_name in observed_teams:
            existing = await session.scalar(
                select(ProviderTeamMapping).where(
                    ProviderTeamMapping.provider == provider,
                    ProviderTeamMapping.provider_team_id == provider_team_id,
                )
            )
            if existing is not None:
                continue
            if observed_name is None:
                continue
            candidates = [
                team_id
                for team_id, team in expected_teams.items()
                if team is not None and _names_match(team.name, observed_name)
            ]
            if len(candidates) != 1:
                continue
            session.add(
                ProviderTeamMapping(
                    provider=provider,
                    provider_team_id=provider_team_id,
                    canonical_team_id=candidates[0],
                    observed_name=observed_name,
                )
            )
            resolved += 1
        if resolved:
            await session.flush()
        return resolved


def _names_match(canonical_name: str, provider_name: str) -> bool:
    return bool(equivalent_team_aliases(canonical_name) & equivalent_team_aliases(provider_name))


async def _merge_placeholder_team(
    session: AsyncSession,
    *,
    source_team_id: UUID,
    target_team_id: UUID,
) -> None:
    references = (
        (TeamAlias, "canonical_team_id"),
        (CanonicalSeries, "team_a_id"),
        (CanonicalSeries, "team_b_id"),
        (OddsObservationRecord, "selection_team_id"),
        (HistoricalMapRecord, "radiant_team_id"),
        (HistoricalMapRecord, "dire_team_id"),
        (HistoricalMapRecord, "winner_team_id"),
        (HistoricalPlayerMapRecord, "canonical_team_id"),
        (HistoricalPlayerMapRecord, "opponent_team_id"),
        (TeamRatingSnapshotRecord, "canonical_team_id"),
        (TeamFormSnapshotRecord, "canonical_team_id"),
        (MapResultRecord, "winner_team_id"),
        (MapResultEvidenceRecord, "winner_team_id"),
    )
    for model, field_name in references:
        field = getattr(model, field_name)
        await session.execute(
            update(model).where(field == source_team_id).values({field_name: target_team_id})
        )
