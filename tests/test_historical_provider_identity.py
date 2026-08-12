from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import Base
from app.history.repository import HistoricalRepository
from app.history.sync import HistoricalSyncService
from app.models import CanonicalTeam, ProviderTeamMapping
from app.providers.common import TimedPayload
from app.repositories.raw import RawEventRepository


class _Provider:
    normalizer_version = "fixture-v1"

    def __init__(self, name: str) -> None:
        self.name = name
        self.team_ids: list[str] = []

    async def get_team_pro_maps(self, team_id: str, **_kwargs) -> TimedPayload:
        self.team_ids.append(team_id)
        return TimedPayload(
            payload={"matches": []},
            request_started_at=datetime(2026, 1, 1, tzinfo=UTC),
            received_at=datetime(2026, 1, 1, tzinfo=UTC),
        )

    async def get_match_advanced(self, _match_id: int) -> TimedPayload:
        raise AssertionError("empty team history should not fetch match details")


@pytest.mark.asyncio
async def test_stratz_never_receives_opendota_team_id() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    primary = _Provider("stratz")
    fallback = _Provider("opendota")

    async with factory() as session, session.begin():
        canonical_team = CanonicalTeam(id=uuid4(), name="Team A")
        session.add(canonical_team)
        await session.flush()
        session.add(
            ProviderTeamMapping(
                provider="opendota",
                provider_team_id="4242",
                canonical_team_id=canonical_team.id,
            )
        )
        service = HistoricalSyncService(
            primary=primary,
            fallback=fallback,
            raw_events=RawEventRepository(),
            repository=HistoricalRepository(),
            concurrency=1,
        )
        result = await service.sync_team(
            session,
            canonical_team_id=canonical_team.id,
            before=datetime(2026, 1, 2, tzinfo=UTC),
            limit=10,
        )

    assert primary.team_ids == []
    assert fallback.team_ids == ["4242"]
    assert "HISTORICAL_PRIMARY_TEAM_IDENTITY_MISSING" in result.warnings
    await engine.dispose()
