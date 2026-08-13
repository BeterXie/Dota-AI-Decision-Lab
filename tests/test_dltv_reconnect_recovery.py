from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import Base
from app.events.outbox import EventRepository
from app.live.collector import DltvSocketCollector
from app.models import CanonicalMap, CanonicalSeries, CanonicalTeam, DomainEventRecord
from app.repositories.raw import RawEventRepository


@pytest.mark.asyncio
async def test_dltv_reconnect_uses_connection_identity_across_generation_reset() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    valve_match_id = 8940730389

    async with factory() as session, session.begin():
        team_a = CanonicalTeam(name="A")
        team_b = CanonicalTeam(name="B")
        session.add_all((team_a, team_b))
        await session.flush()
        series = CanonicalSeries(team_a_id=team_a.id, team_b_id=team_b.id)
        session.add(series)
        await session.flush()
        session.add(CanonicalMap(series_id=series.id, valve_match_id=valve_match_id))

    collector = DltvSocketCollector(
        session_factory=factory,
        raw_events=RawEventRepository(),
        events=EventRepository(),
    )
    started_at = datetime(2026, 8, 14, 0, 0, tzinfo=UTC)
    event_name = f"__nd2_match_{valve_match_id}"

    await collector.collect(
        event_name,
        {},
        "connection-before-restart",
        4,
        received_at=started_at,
    )
    await collector.collect(
        event_name,
        {},
        "connection-after-restart",
        1,
        received_at=started_at + timedelta(seconds=5),
    )
    await collector.collect(
        event_name,
        {},
        "connection-after-restart",
        1,
        received_at=started_at + timedelta(seconds=6),
    )

    async with factory() as session:
        records = list(
            (
                await session.scalars(
                    select(DomainEventRecord).where(
                        DomainEventRecord.event_type == "DLTV_MATCH_DISCOVERED"
                    )
                )
            ).all()
        )

    assert len(records) == 1
    assert records[0].dedupe_key == (f"dltv-reconnect:{valve_match_id}:connection-after-restart")
    assert records[0].payload == {
        "valve_match_id": valve_match_id,
        "connection_id": "connection-after-restart",
        "previous_connection_id": "connection-before-restart",
        "reconnect_generation": 1,
        "previous_reconnect_generation": 4,
        "reason": "SOCKET_RECONNECT_RECOVERY",
    }
    await engine.dispose()
