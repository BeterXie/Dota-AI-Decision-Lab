import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import Base
from app.models import CanonicalMap
from app.shadow_audit import build_shadow_run_audit
from app.shadow_audit_snapshot import snapshot_quality


def test_shadow_snapshot_quality_empty() -> None:
    assert snapshot_quality([])["count"] == 0


@pytest.mark.asyncio
async def test_shadow_audit_runs_for_an_empty_canonical_map() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session, session.begin():
        canonical_map = CanonicalMap(map_number=1, valve_match_id=123456789)
        session.add(canonical_map)
        await session.flush()
        canonical_map_id = canonical_map.id

    async with factory() as session:
        report = await build_shadow_run_audit(
            session,
            canonical_map_id=canonical_map_id,
        )

    assert report["schema_version"] == "shadow-run-audit-v1"
    assert report["map"]["canonical_map_id"] == str(canonical_map_id)
    assert report["snapshots"]["count"] == 0
    assert report["provider_evidence"]["dltv"]["raw_event_count"] == 0
    assert report["ai"]["decision_count"] == 0
    assert report["check_status_counts"] == {"NOT_APPLICABLE": 3, "PASS": 1}
    await engine.dispose()
