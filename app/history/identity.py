from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.identity.aliases import normalize_alias
from app.models import CanonicalTeam, ProviderTeamMapping, TeamAlias
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
                names.setdefault(normalize_alias(team.name), set()).add(team.id)
                for alternate in _known_provider_names(team.name):
                    names.setdefault(normalize_alias(alternate), set()).add(team.id)
            aliases = list(
                (
                    await session.scalars(
                        select(TeamAlias).where(TeamAlias.canonical_team_id == team_id)
                    )
                ).all()
            )
            for alias in aliases:
                names.setdefault(alias.normalized_name, set()).add(team_id)

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


def _known_provider_names(name: str) -> tuple[str, ...]:
    aliases = {
        "liquid": ("Team Liquid",),
        "spirit": ("Team Spirit",),
        "level up": ("Level UP", "Level UP esports"),
        "aurora": ("Aurora Gaming", "Aurora.1xBet"),
    }
    return aliases.get(normalize_alias(name), ())


def _names_match(canonical_name: str, provider_name: str) -> bool:
    normalized_provider = normalize_alias(provider_name)
    return normalized_provider in {
        normalize_alias(canonical_name),
        *(normalize_alias(alias) for alias in _known_provider_names(canonical_name)),
    }
