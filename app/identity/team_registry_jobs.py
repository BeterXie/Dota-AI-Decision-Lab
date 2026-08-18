from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.jobs import DurableJob
from app.identity.team_registry_population import TeamRegistryPopulationService
from app.providers.opendota.client import OpenDotaClient
from app.repositories.raw import RawEventRepository


class TeamRegistryJobHandler:
    """Run registry population independently from RayBet discovery/odds jobs."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        raw_events: RawEventRepository,
        opendota: OpenDotaClient,
    ) -> None:
        self._session_factory = session_factory
        self._population = TeamRegistryPopulationService(raw_events)
        self._opendota = opendota

    async def handle(self, job: DurableJob) -> None:
        raw_team_ids = job.payload.get("canonical_team_ids")
        if not isinstance(raw_team_ids, list) or not raw_team_ids:
            raise ValueError("canonical_team_ids must be a non-empty list")
        try:
            team_ids = [UUID(value) for value in raw_team_ids if isinstance(value, str)]
        except ValueError as exc:
            raise ValueError("canonical_team_ids contains an invalid UUID") from exc
        if len(team_ids) != len(raw_team_ids):
            raise ValueError("canonical_team_ids must contain only UUID strings")

        async with self._session_factory() as session, session.begin():
            await self._population.populate(
                session,
                self._opendota,
                canonical_team_ids=team_ids,
            )
