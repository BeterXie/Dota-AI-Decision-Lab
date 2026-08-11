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
            aliases = list(
                (
                    await session.scalars(
                        select(TeamAlias).where(TeamAlias.canonical_team_id == team_id)
                    )
                ).all()
            )
            for alias in aliases:
                names.setdefault(alias.normalized_name, set()).add(team_id)

        resolved = 0
        unresolved = set(canonical_team_ids)
        for page in range(max_pages):
            response = await client.get_team_catalog(page)
            payload = response.payload
            await self._raw_events.append(
                session,
                provider="opendota",
                event_type="OPENDOTA_TEAM_CATALOG",
                provider_key=str(page),
                payload={"teams": payload} if isinstance(payload, list) else payload,
                request_started_at=response.request_started_at,
                received_at=response.received_at,
                parser_version=client.normalizer_version,
            )
            if not isinstance(payload, list) or not payload:
                break
            for item in payload:
                if not isinstance(item, dict):
                    continue
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
            if not unresolved:
                break
        return resolved
