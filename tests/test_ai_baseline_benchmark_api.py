import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import Base
from app.web.quality import create_quality_router


@pytest.mark.asyncio
async def test_baseline_benchmark_api_returns_frozen_empty_contract() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    app = FastAPI()
    app.include_router(create_quality_router(factory))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/review/ai-quality/benchmark")

    assert response.status_code == 200
    payload = response.json()
    assert payload["benchmark_report_version"] == "ai-benchmark-v2"
    assert payload["baseline_contract"] == {
        "id": "production-baseline-v1",
        "frozen_at_commit": "81698ca175a75dfb08285c3725c98835f616a843",
        "prompt_version": "decision-analyst-v5.1-output",
        "decision_policy_version": "shadow-tournament-portfolio-v3",
        "ai_view_version": "ai-view-v6",
        "models_by_provider": {
            "openai": "gpt-5.6-terra",
            "anthropic": "claude-sonnet-4-6",
            "gemini": "gemini-3.6-flash",
            "deepseek": "deepseek-v4-pro",
        },
        "immutable": True,
    }
    assert payload["methodology"]["forecast_sample"] == "FIRST_EVALUABLE_FORECAST_PER_MAP"
    assert payload["experiments"] == []
    await engine.dispose()
