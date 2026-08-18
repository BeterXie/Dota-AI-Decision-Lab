from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import Base
from app.identity.roster_models import TeamRosterMembership
from app.identity.roster_sync import TeamRosterSyncService
from app.models import CanonicalTeam, ProviderTeamMapping
from app.providers.common import TimedPayload
from app.repositories.raw import RawEventRepository


class FakeOpenDotaClient:
    normalizer_version = "test-opendota"

    def __init__(self, payloads: list[list[dict]]) -> None:
        self.payloads = payloads
        self.calls = 0

    async def get_team_players(self, team_id: int) -> TimedPayload:
        payload = self.payloads[self.calls]
        received_at = datetime(2026, 8, 18, 2, 0, tzinfo=UTC) + timedelta(hours=self.calls)
        self.calls += 1
        return TimedPayload(
            payload=payload,
            request_started_at=received_at - timedelta(seconds=1),
            received_at=received_at,
        )


@pytest.mark.asyncio
async def test_roster_sync_creates_and_closes_only_discovered_player_memberships() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory.begin() as session:
        team = CanonicalTeam(name="Roster Team")
        session.add(team)
        await session.flush()
        session.add(
            ProviderTeamMapping(
                provider="opendota",
                provider_team_id="7654321",
                canonical_team_id=team.id,
                observed_name="Roster Team",
            )
        )

    client = FakeOpenDotaClient(
        [
            [
                {"account_id": 101, "name": "Carry", "is_current_team_member": True},
                {"account_id": 102, "name": "Mid", "is_current_team_member": True},
                {"account_id": 999, "name": "Old", "is_current_team_member": False},
            ],
            [
                {"account_id": 101, "name": "Carry", "is_current_team_member": True},
            ],
        ]
    )
    service = TeamRosterSyncService(RawEventRepository())

    async with factory.begin() as session:
        first = await service.sync_team(session, client, canonical_team_id=team.id)  # type: ignore[arg-type]
    assert first.current_players == 2
    assert first.created_players == 2
    assert first.created_memberships == 2
    assert first.closed_memberships == 0

    async with factory.begin() as session:
        second = await service.sync_team(session, client, canonical_team_id=team.id)  # type: ignore[arg-type]
    assert second.current_players == 1
    assert second.created_players == 0
    assert second.created_memberships == 0
    assert second.closed_memberships == 1

    async with factory() as session:
        memberships = list(
            (
                await session.scalars(
                    select(TeamRosterMembership).where(TeamRosterMembership.team_id == team.id)
                )
            ).all()
        )
    active = [item for item in memberships if item.valid_to is None]
    closed = [item for item in memberships if item.valid_to is not None]
    assert len(active) == 1
    assert len(closed) == 1
    assert all(item.source_name == "opendota" for item in memberships)

    await engine.dispose()
