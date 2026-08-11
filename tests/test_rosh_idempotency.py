from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import Base
from app.draft.engine import MODEL_VERSION
from app.draft.rosh_service import RoshService
from app.models import DraftMinuteCurveRecord, DraftSnapshotRecord
from app.repositories.raw import RawEventRepository


class FailingStratzClient:
    async def execute(self, **_kwargs):
        raise AssertionError("an existing immutable curve must not refetch STRATZ")


@pytest.mark.asyncio
async def test_rosh_build_reuses_existing_curve_after_job_restart() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    canonical_map_id = uuid4()
    draft_snapshot_id = uuid4()
    cutoff = datetime(2026, 8, 12, tzinfo=UTC)

    async with factory() as session, session.begin():
        session.add(
            DraftSnapshotRecord(
                id=draft_snapshot_id,
                canonical_map_id=canonical_map_id,
                valve_match_id=8940730389,
                complete=True,
                blockers=[],
                warnings=[],
                payload_hash="draft-fixture",
                statistics_cutoff=cutoff,
                observed_at=cutoff,
                raw_event_id=uuid4(),
            )
        )
        session.add(
            DraftMinuteCurveRecord(
                canonical_map_id=canonical_map_id,
                draft_snapshot_id=draft_snapshot_id,
                points=[
                    {
                        "minute": 20,
                        "pure_radiant_edge": 1.2,
                        "adjusted_radiant_edge": 1.5,
                        "support": 42,
                        "confidence": None,
                    }
                ],
                derived_features={"current_minute": 20, "current_edge": 1.5},
                statistics_cutoff=cutoff,
                model_version=MODEL_VERSION,
                data_version="fixture-v1",
            )
        )

    service = RoshService(FailingStratzClient(), RawEventRepository())
    async with factory() as session, session.begin():
        curve = await service.build(
            session,
            canonical_map_id=canonical_map_id,
            draft_snapshot_id=draft_snapshot_id,
        )

    assert curve.model_version == MODEL_VERSION
    assert curve.data_version == "fixture-v1"
    assert curve.points[0].adjusted_radiant_edge == 1.5
    await engine.dispose()
