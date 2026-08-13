from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import Base
from app.draft.role_assignment import DraftRoleAssignmentService
from app.providers.common import TimedPayload
from app.providers.dltv.draft_picks import DltvProviderPick
from app.repositories.raw import RawEventRepository


class _DotaPositionClient:
    def __init__(self, received_at: datetime) -> None:
        self.received_at = received_at

    async def execute(self, *, operation_name: str, query: str, variables: dict) -> TimedPayload:
        players = []
        for radiant, account_start, hero_start in ((True, 1000, 10), (False, 2000, 20)):
            for provider_slot in range(1, 6):
                players.append({
                    "steamAccountId": account_start + provider_slot,
                    "heroId": hero_start + provider_slot,
                    "position": f"POSITION_{6 - provider_slot}",
                    "isRadiant": radiant,
                })
        return TimedPayload(
            payload={"data": {"match": {"id": variables["matchId"], "players": players}}},
            request_started_at=self.received_at - timedelta(milliseconds=100),
            received_at=self.received_at,
        )


def _picks() -> tuple[DltvProviderPick, ...]:
    rows = []
    for side, account_start, hero_start in (("radiant", 1000, 10), ("dire", 2000, 20)):
        for provider_slot in range(1, 6):
            rows.append(DltvProviderPick(
                side=side,
                provider_slot=provider_slot,
                account_id=account_start + provider_slot,
                hero_id=hero_start + provider_slot,
            ))
    return tuple(rows)


@pytest.mark.asyncio
async def test_explicit_dota_positions_override_provider_ordering() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    observed_at = datetime(2026, 8, 14, 1, 0, tzinfo=UTC)
    service = DraftRoleAssignmentService(
        stratz=_DotaPositionClient(observed_at + timedelta(seconds=1)),
        raw_events=RawEventRepository(),
    )
    async with factory() as session, session.begin():
        result = await service.resolve(session, valve_match_id=42, picks=_picks(), observed_at=observed_at)
    by_account = {slot.account_id: slot for slot in result.draft.slots}
    assert result.draft.complete is True
    assert by_account[1001].position == 5
    assert by_account[1005].position == 1
    assert by_account[1001].position != 1
    assert all(slot.source == "STRATZ_CURRENT_MATCH" for slot in result.draft.slots)
    await engine.dispose()
