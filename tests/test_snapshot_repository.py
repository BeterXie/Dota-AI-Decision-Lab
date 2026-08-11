from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import Base
from app.models import DecisionSnapshotRecord
from app.snapshots.repository import SnapshotRepository


@pytest.mark.asyncio
async def test_snapshot_is_deterministic_idempotent_and_immutable() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    repository = SnapshotRepository()
    decision_at = datetime(2026, 1, 1, tzinfo=UTC)

    async with factory() as session, session.begin():
        first = await repository.persist(
            session,
            canonical_map_id=None,
            decision_at=decision_at,
            mode="PREMATCH",
            identity={"map_id": None},
            market={"price": "2.00"},
            draft=None,
            history={"unknown_metric": None},
            live=None,
            quality={"eligible": True, "blockers": [], "warnings": []},
        )
        second = await repository.persist(
            session,
            canonical_map_id=None,
            decision_at=decision_at,
            mode="PREMATCH",
            identity={"map_id": None},
            market={"price": "2.00"},
            draft=None,
            history={"unknown_metric": None},
            live=None,
            quality={"eligible": True, "blockers": [], "warnings": []},
        )

    assert first.snapshot_id == second.snapshot_id
    assert first.snapshot_hash == second.snapshot_hash
    async with factory() as session:
        count = await session.scalar(select(func.count()).select_from(DecisionSnapshotRecord))
        record = await session.get(DecisionSnapshotRecord, first.snapshot_id)
        assert count == 1
        assert record is not None
        assert record.canonical_payload["history"]["unknown_metric"] is None
        record.mode = "POST_DRAFT"
        with pytest.raises(ValueError, match="immutable"):
            await session.flush()
        await session.rollback()

    await engine.dispose()
