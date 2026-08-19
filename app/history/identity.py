from uuid import UUID

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.identity.aliases import equivalent_team_aliases, normalize_alias
from app.models import (
    CanonicalMap,
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
            if observed_name is None:
                continue
            candidates = [
                team_id
                for team_id, team in expected_teams.items()
                if team is not None and _names_match(team.name, observed_name)
            ]
            if len(candidates) != 1:
                continue
            canonical_team_id = candidates[0]
            existing = await session.scalar(
                select(ProviderTeamMapping).where(
                    ProviderTeamMapping.provider == provider,
                    ProviderTeamMapping.provider_team_id == provider_team_id,
                )
            )
            if existing is not None:
                if existing.canonical_team_id == canonical_team_id:
                    existing.observed_name = existing.observed_name or observed_name
                    continue
                placeholder = await session.get(CanonicalTeam, existing.canonical_team_id)
                if placeholder is None or not _is_generated_provider_team(
                    placeholder.name,
                    provider=provider,
                    provider_team_id=provider_team_id,
                ):
                    continue
                await _merge_placeholder_team(
                    session,
                    source_team_id=placeholder.id,
                    target_team_id=canonical_team_id,
                )
                existing.canonical_team_id = canonical_team_id
                existing.observed_name = observed_name
                await session.delete(placeholder)
                resolved += 1
                continue
            session.add(
                ProviderTeamMapping(
                    provider=provider,
                    provider_team_id=provider_team_id,
                    canonical_team_id=canonical_team_id,
                    observed_name=observed_name,
                )
            )
            resolved += 1
        if resolved:
            await session.flush()
        return resolved

    async def repair_match_placeholders(
        self,
        session: AsyncSession,
        *,
        provider_match_id: str,
        expected_team_ids: set[UUID],
    ) -> int:
        """Merge generated team placeholders when match context makes identity unique."""

        if len(expected_team_ids) != 2:
            return 0
        facts = list(
            (
                await session.scalars(
                    select(HistoricalMapRecord).where(
                        HistoricalMapRecord.provider_match_id == provider_match_id
                    )
                )
            ).all()
        )
        merged: dict[UUID, UUID] = {}
        resolved = 0
        for fact in facts:
            side_ids = {
                merged.get(team_id, team_id)
                for team_id in (fact.radiant_team_id, fact.dire_team_id)
                if team_id is not None
            }
            known = side_ids & expected_team_ids
            unresolved = side_ids - expected_team_ids
            remaining = expected_team_ids - known
            if len(known) != 1 or len(unresolved) != 1 or len(remaining) != 1:
                continue
            source_team_id = next(iter(unresolved))
            target_team_id = next(iter(remaining))
            if source_team_id in merged:
                continue
            mappings = list(
                (
                    await session.scalars(
                        select(ProviderTeamMapping).where(
                            ProviderTeamMapping.provider == fact.provider,
                            ProviderTeamMapping.canonical_team_id == source_team_id,
                        )
                    )
                ).all()
            )
            if len(mappings) != 1:
                continue
            mapping = mappings[0]
            placeholder = await session.get(CanonicalTeam, source_team_id)
            if placeholder is None or not _is_generated_provider_team(
                placeholder.name,
                provider=fact.provider,
                provider_team_id=mapping.provider_team_id,
            ):
                continue
            await _merge_placeholder_team(
                session,
                source_team_id=source_team_id,
                target_team_id=target_team_id,
            )
            mapping.canonical_team_id = target_team_id
            await session.delete(placeholder)
            await session.flush()
            merged[source_team_id] = target_team_id
            resolved += 1
        return resolved


def _names_match(canonical_name: str, provider_name: str) -> bool:
    return bool(equivalent_team_aliases(canonical_name) & equivalent_team_aliases(provider_name))


def _is_generated_provider_team(
    name: str,
    *,
    provider: str,
    provider_team_id: str,
) -> bool:
    return name == f"{provider.upper()} team {provider_team_id}"


async def _merge_placeholder_team(
    session: AsyncSession,
    *,
    source_team_id: UUID,
    target_team_id: UUID,
) -> None:
    affected_provider_match_ids = set(
        (
            await session.scalars(
                select(HistoricalMapRecord.provider_match_id).where(
                    or_(
                        HistoricalMapRecord.radiant_team_id == source_team_id,
                        HistoricalMapRecord.dire_team_id == source_team_id,
                        HistoricalMapRecord.winner_team_id == source_team_id,
                    )
                )
            )
        ).all()
    )
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
    await session.flush()
    await _restore_converged_match_results(session, affected_provider_match_ids)


async def _restore_converged_match_results(
    session: AsyncSession,
    provider_match_ids: set[str],
) -> None:
    for provider_match_id in provider_match_ids:
        facts = list(
            (
                await session.scalars(
                    select(HistoricalMapRecord).where(
                        HistoricalMapRecord.provider_match_id == provider_match_id
                    )
                )
            ).all()
        )
        if len({fact.provider for fact in facts}) < 2:
            continue
        if any(
            fact.canonical_map_id is None
            or fact.radiant_team_id is None
            or fact.dire_team_id is None
            or fact.winner_team_id is None
            for fact in facts
        ):
            continue
        map_ids = {fact.canonical_map_id for fact in facts}
        winners = {fact.winner_team_id for fact in facts}
        team_pairs = {frozenset((fact.radiant_team_id, fact.dire_team_id)) for fact in facts}
        if len(map_ids) != 1 or len(winners) != 1 or len(team_pairs) != 1:
            continue
        canonical_map_id = next(iter(map_ids))
        winner_team_id = next(iter(winners))
        canonical_map = await session.get(CanonicalMap, canonical_map_id)
        series = (
            await session.get(CanonicalSeries, canonical_map.series_id)
            if canonical_map is not None and canonical_map.series_id is not None
            else None
        )
        if series is None:
            continue
        expected_team_ids = {series.team_a_id, series.team_b_id}
        if next(iter(team_pairs)) != expected_team_ids or winner_team_id not in expected_team_ids:
            continue

        for fact in facts:
            if fact.sync_status == "DATA_CONFLICT":
                fact.sync_status = (
                    "ADVANCED_READY" if fact.advanced_ready_at is not None else "BASIC_READY"
                )

        evidence_rows = list(
            (
                await session.scalars(
                    select(MapResultEvidenceRecord).where(
                        MapResultEvidenceRecord.canonical_map_id == canonical_map_id
                    )
                )
            ).all()
        )
        if not evidence_rows or any(
            evidence.winner_team_id != winner_team_id for evidence in evidence_rows
        ):
            continue
        for evidence in evidence_rows:
            evidence.conflict_status = "CONFIRMED"
        result = await session.scalar(
            select(MapResultRecord).where(MapResultRecord.canonical_map_id == canonical_map_id)
        )
        if result is not None:
            result.winner_team_id = winner_team_id
            result.provider_conflict = False
