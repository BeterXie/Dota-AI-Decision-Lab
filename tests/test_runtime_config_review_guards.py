from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.runtime_config.service as runtime_service
from app.ai.base import AiProviderResponse, ai_decision_lane_key
from app.ai.coordinator import PreparedAiDecision
from app.db import Base
from app.domain.decision import AiDecision
from app.domain.experiment import ai_experiment_key
from app.evaluation.benchmark import AiBaselineBenchmarkService, _ExperimentAccumulator
from app.runtime_config.ai_coordinator import (
    RuntimeAiCoordinator,
    _execution_config_version,
)
from app.runtime_config.models import AiProviderConfigRecord
from app.runtime_config.policy import AiDecisionPolicySnapshot
from app.runtime_config.provider_safety import validate_provider_base_url
from app.web.feature_flags import RuntimeFeatureFlagMiddleware
from app.web.runtime_admin import _validated_provider_changes


class _Provider:
    name = "openai"
    model = "startup-model"

    async def decide(self, snapshot_input: str):
        raise AssertionError("not used")

    async def close(self) -> None:
        return None


def _provider_row(
    *,
    slot: str = "default",
    model: str = "gpt-5.6-terra",
    reasoning: str = "high",
    timeout: float = 30.0,
) -> AiProviderConfigRecord:
    return AiProviderConfigRecord(
        provider="openai",
        slot=slot,
        enabled=True,
        decisions_enabled=True,
        base_url="https://api.openai.com/v1",
        model=model,
        reasoning_effort=reasoning,
        timeout_seconds=timeout,
        api_key_secret_key="ai.openai.api_key",
    )


def test_cloud_provider_base_url_accepts_https_relays_and_local_http() -> None:
    assert (
        validate_provider_base_url("openai", "https://api.openai.com/v1/")
        == "https://api.openai.com/v1"
    )
    assert (
        validate_provider_base_url("openai", "https://api.quya.org/v1") == "https://api.quya.org/v1"
    )
    assert (
        validate_provider_base_url("anthropic", "https://relay.example/anthropic")
        == "https://relay.example/anthropic"
    )
    assert (
        validate_provider_base_url("local_openai", "http://127.0.0.1:11434/v1")
        == "http://127.0.0.1:11434/v1"
    )
    with pytest.raises(ValueError, match="must use https"):
        validate_provider_base_url("deepseek", "http://api.deepseek.com")
    with pytest.raises(ValueError, match="must not contain user credentials"):
        validate_provider_base_url("openai", "https://user:password@relay.example/v1")


@pytest.mark.asyncio
async def test_provider_model_identity_is_unique_across_slots() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            session.add_all(
                [
                    AiProviderConfigRecord(
                        provider="deepseek",
                        slot="flash",
                        enabled=True,
                        decisions_enabled=False,
                        base_url="https://api.deepseek.com",
                        model="same-model",
                        reasoning_effort="high",
                        timeout_seconds=30,
                        api_key_secret_key="ai.deepseek.api_key",
                    ),
                    AiProviderConfigRecord(
                        provider="deepseek",
                        slot="pro",
                        enabled=True,
                        decisions_enabled=True,
                        base_url="https://api.deepseek.com",
                        model="same-model",
                        reasoning_effort="high",
                        timeout_seconds=30,
                        api_key_secret_key="ai.deepseek.api_key",
                    ),
                ]
            )
            with pytest.raises(IntegrityError):
                await session.commit()
    finally:
        await engine.dispose()


def test_runtime_coordinator_keeps_last_known_provider_set_across_cache_invalidation() -> None:
    original = runtime_service._ACTIVE_EXPERIMENT_CACHE
    try:
        coordinator = RuntimeAiCoordinator([_Provider()], timeout_seconds=10)
        hot = (ai_decision_lane_key("kimi", "hot-model"),)
        runtime_service._ACTIVE_EXPERIMENT_CACHE = hot
        assert coordinator.experiments == hot
        runtime_service._ACTIVE_EXPERIMENT_CACHE = None
        assert coordinator.experiments == hot
        runtime_service._ACTIVE_EXPERIMENT_CACHE = ()
        assert coordinator.experiments == ()
    finally:
        runtime_service._ACTIVE_EXPERIMENT_CACHE = original


def test_execution_config_version_tracks_runtime_revision_and_input_policy() -> None:
    row = _provider_row()
    policy = AiDecisionPolicySnapshot(
        enabled=True,
        max_live_data_lag_seconds=120,
        prior_decisions_limit=10,
    )
    first = _execution_config_version(row, policy)
    row.reasoning_effort = "low"
    row.revision = 2
    second = _execution_config_version(row, policy)
    changed_policy = AiDecisionPolicySnapshot(
        enabled=True,
        max_live_data_lag_seconds=90,
        prior_decisions_limit=10,
    )
    third = _execution_config_version(row, changed_policy)

    assert first != second
    assert second != third
    assert first == "openai:default:r1:lag120:prior10"
    assert "api_key" not in first


@pytest.mark.asyncio
async def test_runtime_inference_persists_config_version_outside_model_version() -> None:
    class _ManagedProvider:
        name = "openai"
        model = "gpt-5.6-sol"
        runtime_config_managed = True
        runtime_execution_config_version = "openai:default:r2:lag120:prior10"
        runtime_timeout_seconds = 10.0

        async def decide(self, snapshot_input: str) -> AiProviderResponse:
            return AiProviderResponse(
                raw_response={"ok": True},
                decision=AiDecision(
                    action="NO_BUY",
                    fair_probability_a=0.5,
                    confidence=0.5,
                    market_assessment="FAIR",
                    minimum_acceptable_odds_a=None,
                    stake=None,
                    primary_reasons=[],
                    blockers=[],
                ),
                model_version="provider-release-2026-08",
            )

        async def close(self) -> None:
            return None

    now = datetime.now(UTC)
    provider = _ManagedProvider()
    prepared = PreparedAiDecision(
        provider=provider,
        snapshot=SimpleNamespace(snapshot_id=uuid4(), snapshot_hash="snapshot-hash"),
        provider_input="{}",
        ai_input_hash="input-hash",
        bankroll_before=10_000.0,
        input_prepare_started_at=now,
        input_prepare_completed_at=now,
        execution_config_version=provider.runtime_execution_config_version,
    )

    record = await RuntimeAiCoordinator([provider], timeout_seconds=10).run_inference(prepared)

    assert record.model_version == "provider-release-2026-08"
    assert record.execution_config_version == "openai:default:r2:lag120:prior10"


def test_benchmark_uses_explicit_execution_config_identity() -> None:
    acc = _ExperimentAccumulator(
        attempts=2,
        successful_attempts=2,
        model_versions={"provider-release-a", "provider-release-b"},
        latencies=[1.0, 3.0],
    )
    row = AiBaselineBenchmarkService()._build_experiment_row(
        ai_experiment_key(
            ai_decision_lane_key("openai", "gpt-5.6-terra"),
            "openai:default:r2:lag120:prior10",
        ),
        acc,
        {
            "event_count": 2,
            "realized_roi": 0.2,
            "realized_pnl": 100,
            "worst_event_drawdown_pct": 0.1,
            "bet_count": 5,
        },
    )

    assert row["execution_config"] == {
        "version": "openai:default:r2:lag120:prior10",
        "mixed": False,
        "comparison_eligible": True,
        "blocker": None,
    }
    assert row["latency"]["average_seconds"] == 2.0
    assert row["portfolio"]["realized_roi"] == 0.2


class _FakeService:
    async def public_payload(self):
        return {
            "ai_providers": [
                {
                    "provider": "deepseek",
                    "slot": "flash",
                    "enabled": True,
                    "decisions_enabled": False,
                    "base_url": "https://api.deepseek.com",
                    "model": "flash-model",
                    "api_key_secret_key": "ai.deepseek.api_key",
                },
                {
                    "provider": "deepseek",
                    "slot": "pro",
                    "enabled": True,
                    "decisions_enabled": True,
                    "base_url": "https://api.deepseek.com",
                    "model": "pro-model",
                    "api_key_secret_key": "ai.deepseek.api_key",
                },
            ]
        }


class _FakeAdminPolicy:
    def __init__(self, *, operational: bool) -> None:
        self.operational = operational

    async def secret_status_payload(self):
        return {
            "items": [
                {
                    "key": "ai.deepseek.api_key",
                    "operational": self.operational,
                }
            ]
        }


@pytest.mark.asyncio
async def test_admin_provider_guard_rejects_ambiguous_model_unsafe_url_and_missing_secret() -> None:
    service = _FakeService()
    with pytest.raises(ValueError, match="already belongs to another slot"):
        await _validated_provider_changes(
            service,
            _FakeAdminPolicy(operational=True),
            "deepseek",
            "flash",
            {"model": "pro-model"},
        )
    with pytest.raises(ValueError, match="must not contain user credentials"):
        await _validated_provider_changes(
            service,
            _FakeAdminPolicy(operational=True),
            "deepseek",
            "flash",
            {
                "base_url": "https://user:password@relay.example",
                "decisions_enabled": False,
            },
        )
    with pytest.raises(ValueError, match="credential is not operational"):
        await _validated_provider_changes(
            service,
            _FakeAdminPolicy(operational=False),
            "deepseek",
            "flash",
            {"decisions_enabled": True},
        )


class _DisabledPerformancePolicy:
    async def feature_enabled(self, key: str) -> bool:
        return key != "feature.performance.enabled"


@pytest.mark.asyncio
async def test_performance_flag_blocks_legacy_ai_performance_endpoint_too() -> None:
    app = FastAPI()
    app.add_middleware(RuntimeFeatureFlagMiddleware, policy=_DisabledPerformancePolicy())

    @app.get("/api/ai-performance")
    async def legacy_performance():
        return {"ok": True}

    @app.get("/api/review/ai-quality/benchmark")
    async def benchmark():
        return {"ok": True}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        legacy = await client.get("/api/ai-performance")
        review = await client.get("/api/review/ai-quality/benchmark")

    assert legacy.status_code == 503
    assert review.status_code == 503
