from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.db import Base
from app.domain.jobs import DurableJob, JobStatus, JobType
from app.history.sync import HistoricalSyncResult
from app.jobs.handlers import ApplicationJobHandlers
from app.models import CanonicalSeries, CanonicalTeam, ProviderTeamMapping
from app.runtime.health import HealthRegistry


class _FailingSecondTeamSync:
    def __init__(self) -> None:
        self.calls = 0

    async def sync_team(self, session, **_kwargs) -> HistoricalSyncResult:
        self.calls += 1
        if self.calls == 2:
            raise RuntimeError("second team provider timeout")
        session.add(CanonicalTeam(name="partial historical write"))
        return HistoricalSyncResult(
            provider="opendota",
            maps_requested=1,
            maps_fetched=1,
            maps_normalized=1,
            maps_canonicalized=1,
            maps_eligible_team_rating=1,
            maps_eligible_player_form=1,
            maps_advanced_ready=0,
            identity_missing_count=0,
            provider_fallback_count=0,
            conflict_count=0,
            warnings=(),
        )


class _HistoricalFeatures:
    def __init__(self) -> None:
        self.calls = 0

    async def build_team_ratings(self, *_args, **_kwargs) -> None:
        self.calls += 1

    async def build_role_baselines(self, *_args, **_kwargs) -> None:
        self.calls += 1


@pytest.mark.asyncio
async def test_historical_sync_failure_rolls_back_partial_team_and_retries_job() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session, session.begin():
        team_a = CanonicalTeam(name="Team A")
        team_b = CanonicalTeam(name="Team B")
        session.add_all((team_a, team_b))
        await session.flush()
        series = CanonicalSeries(team_a_id=team_a.id, team_b_id=team_b.id)
        session.add(series)
        await session.flush()
        session.add_all(
            (
                ProviderTeamMapping(
                    provider="opendota",
                    provider_team_id="100",
                    canonical_team_id=team_a.id,
                ),
                ProviderTeamMapping(
                    provider="opendota",
                    provider_team_id="200",
                    canonical_team_id=team_b.id,
                ),
            )
        )
        series_id = series.id

    sync = _FailingSecondTeamSync()
    features = _HistoricalFeatures()
    health = HealthRegistry()
    handlers = ApplicationJobHandlers(
        SimpleNamespace(
            session_factory=factory,
            settings=Settings(_env_file=None),
            historical_team_resolver=object(),
            historical_primary=None,
            historical_sync=sync,
            historical_features=features,
            opendota=object(),
            health=health,
        )
    )
    now = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)
    job = DurableJob(
        id=uuid4(),
        job_type=JobType.SYNC_HISTORICAL,
        dedupe_key="historical-failure",
        payload={"canonical_series_id": str(series_id)},
        status=JobStatus.RUNNING,
        priority=100,
        not_before=now,
        created_at=now,
        attempt_count=1,
        max_attempts=8,
        locked_by="test",
        locked_at=now,
    )

    with pytest.raises(RuntimeError, match="historical sync incomplete"):
        await handlers.sync_historical(job)

    assert sync.calls == 2
    assert features.calls == 0
    async with factory() as session:
        partial_count = await session.scalar(
            select(func.count())
            .select_from(CanonicalTeam)
            .where(CanonicalTeam.name == "partial historical write")
        )
    assert partial_count == 0
    dependency = (await health.snapshot())["dependencies"]["HISTORY"]
    assert dependency["status"] == "DEGRADED"
    assert "second team provider timeout" in dependency["message"]
    await engine.dispose()
