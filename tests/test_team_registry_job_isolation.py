from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import Base
from app.domain.jobs import DurableJob, JobStatus, JobType
from app.identity.roster_models import TeamProfile, TeamRosterMembership
from app.identity.team_registry_jobs import TeamRegistryJobHandler
from app.models import CanonicalSeries, CanonicalTeam, ProviderMatchMapping, ProviderTeamMapping
from app.providers.common import TimedPayload
from app.repositories.raw import RawEventRepository


class FakeOpenDotaClient:
    normalizer_version = "test-opendota"

    def __init__(self) -> None:
        self.observed_at = datetime(2026, 8, 18, 3, 0, tzinfo=UTC)

    async def get_team_catalog(self, page: int = 0) -> TimedPayload:
        return TimedPayload(
            payload=[{"team_id": 7654321, "name": "Team Example", "tag": "EX"}],
            request_started_at=self.observed_at - timedelta(seconds=1),
            received_at=self.observed_at,
        )

    async def get_team_players(self, team_id: str | int) -> TimedPayload:
        assert int(team_id) == 7654321
        return TimedPayload(
            payload=[{"account_id": 101, "name": "Carry", "is_current_team_member": True}],
            request_started_at=self.observed_at,
            received_at=self.observed_at + timedelta(seconds=1),
        )


@pytest.mark.asyncio
async def test_registry_job_resolves_opendota_without_rewriting_raybet_identity() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime(2026, 8, 18, 3, 0, tzinfo=UTC)

    async with factory.begin() as session:
        team = CanonicalTeam(name="Team Example")
        opponent = CanonicalTeam(name="Opponent")
        session.add_all((team, opponent))
        await session.flush()
        series = CanonicalSeries(team_a_id=team.id, team_b_id=opponent.id)
        session.add(series)
        await session.flush()
        session.add_all(
            (
                ProviderTeamMapping(
                    provider="raybet",
                    provider_team_id="501",
                    canonical_team_id=team.id,
                    observed_name="Team Example",
                ),
                ProviderTeamMapping(
                    provider="raybet",
                    provider_team_id="502",
                    canonical_team_id=opponent.id,
                    observed_name="Opponent",
                ),
                ProviderMatchMapping(
                    provider="raybet",
                    provider_match_id="9001",
                    canonical_series_id=series.id,
                    resolved_by="PROVIDER_DISCOVERY",
                    confidence=1.0,
                ),
            )
        )

    handler = TeamRegistryJobHandler(
        session_factory=factory,
        raw_events=RawEventRepository(),
        opendota=FakeOpenDotaClient(),
    )
    job = DurableJob(
        id=uuid4(),
        job_type=JobType.SYNC_TEAM_REGISTRY,
        dedupe_key="team-registry:test:discovered",
        payload={"canonical_team_ids": [str(team.id)]},
        status=JobStatus.PENDING,
        priority=120,
        not_before=now,
        created_at=now,
        attempt_count=0,
        max_attempts=8,
        locked_by=None,
        locked_at=None,
    )
    await handler.handle(job)

    async with factory() as session:
        opendota_mapping = await session.scalar(
            select(ProviderTeamMapping).where(
                ProviderTeamMapping.provider == "opendota",
                ProviderTeamMapping.canonical_team_id == team.id,
            )
        )
        raybet_team_mapping = await session.scalar(
            select(ProviderTeamMapping).where(
                ProviderTeamMapping.provider == "raybet",
                ProviderTeamMapping.provider_team_id == "501",
            )
        )
        raybet_match_mapping = await session.scalar(
            select(ProviderMatchMapping).where(
                ProviderMatchMapping.provider == "raybet",
                ProviderMatchMapping.provider_match_id == "9001",
            )
        )
        profile = await session.get(TeamProfile, team.id)
        roster = list(
            (
                await session.scalars(
                    select(TeamRosterMembership).where(
                        TeamRosterMembership.team_id == team.id,
                        TeamRosterMembership.valid_to.is_(None),
                    )
                )
            ).all()
        )

    assert opendota_mapping is not None
    assert opendota_mapping.provider_team_id == "7654321"
    assert raybet_team_mapping is not None
    assert raybet_team_mapping.canonical_team_id == team.id
    assert raybet_match_mapping is not None
    assert raybet_match_mapping.canonical_series_id == series.id
    assert raybet_match_mapping.resolved_by == "PROVIDER_DISCOVERY"
    assert profile is not None
    assert profile.slug == "team-example"
    assert len(roster) == 1

    await engine.dispose()
