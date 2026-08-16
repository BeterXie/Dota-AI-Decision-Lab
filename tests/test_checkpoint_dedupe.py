from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import Base
from app.events.outbox import EventRepository
from app.models import DomainEventRecord
from app.snapshots.triggers import record_crossed_checkpoints


@pytest.mark.asyncio
async def test_real_time_basis_cannot_duplicate_existing_game_time_checkpoint() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    map_id = uuid4()
    observed_at = datetime(2026, 8, 16, tzinfo=UTC)
    events = EventRepository()
    async with factory() as session, session.begin():
        await record_crossed_checkpoints(
            session,
            events,
            canonical_map_id=map_id,
            previous_game_time=599,
            current_game_time=600,
            checkpoint_minutes=(10,),
            observed_at=observed_at,
        )
        await record_crossed_checkpoints(
            session,
            events,
            canonical_map_id=map_id,
            previous_game_time=600,
            current_game_time=600,
            checkpoint_minutes=(10,),
            observed_at=observed_at,
            previous_real_elapsed_seconds=599,
            real_elapsed_seconds=600,
        )
    async with factory() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(DomainEventRecord)
            .where(DomainEventRecord.aggregate_id == str(map_id))
        )
        assert count == 1
    await engine.dispose()
