from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import Base
from app.runtime.health import HealthRegistry
from app.web.api import create_app


@pytest.mark.asyncio
async def test_operational_api_contract_without_business_data(tmp_path: Path) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    health = HealthRegistry()
    await health.dependency("DATABASE", "READY")
    for provider in ("GPT", "CLAUDE", "GEMINI"):
        await health.dependency(provider, "ACTION_REQUIRED")
    app = create_app(factory, health, frontend_dist=tmp_path / "missing")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        process = await client.get("/health")
        readiness = await client.get("/ready")
        maps = await client.get("/api/maps")
        jobs = await client.get("/api/jobs/summary")
        missing = await client.get("/api/maps/11111111-1111-1111-1111-111111111111")

    assert process.status_code == 200
    assert readiness.status_code == 503
    assert readiness.json()["overall"] == "ACTION_REQUIRED"
    assert maps.status_code == 200 and maps.json() == []
    assert jobs.status_code == 200
    assert jobs.json() == {
        "by_status": {},
        "by_type": [],
        "oldest_pending_at": None,
        "recent_failures": [],
    }
    assert missing.status_code == 404
    await engine.dispose()
