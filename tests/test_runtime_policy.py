import json

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.auth.social import SocialAuthSettings
from app.config import Settings
from app.db import Base
from app.runtime_config import (
    RuntimeConfigurationService,
    RuntimePolicyService,
    active_ai_experiments,
    ai_decision_policy_snapshot,
)
from app.runtime_config.models import RuntimeConfigAuditRecord
from app.web.feature_flags import RuntimeFeatureFlagMiddleware


async def _services():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    settings = Settings(
        _env_file=None,
        openai_api_key=SecretStr("bootstrap-openai-key"),
        openai_model="runtime-policy-model",
        ai_max_live_data_lag_seconds=120,
        ai_prior_decisions_limit=10,
        ai_worker_concurrency=4,
    )
    social = SocialAuthSettings(
        _env_file=None,
        google_enabled=True,
        google_client_id="client.apps.googleusercontent.com",
        google_client_secret=SecretStr("bootstrap-google-secret"),
        external_base_url="http://127.0.0.1:5173",
    )
    config = RuntimeConfigurationService(
        factory,
        settings=settings,
        social_settings=social,
    )
    policy = RuntimePolicyService(
        factory,
        settings=settings,
        social_settings=social,
    )
    return engine, factory, config, policy


@pytest.mark.asyncio
async def test_runtime_ai_policy_updates_are_typed_audited_and_hot() -> None:
    engine, factory, _config, policy = await _services()
    try:
        await policy.ensure_seeded(actor="bootstrap")
        await policy.set_setting(
            "ai.max_live_data_lag_seconds",
            90,
            actor="dev@localhost",
        )
        await policy.set_setting(
            "ai.prior_decisions_limit",
            18,
            actor="dev@localhost",
        )

        async with factory() as session:
            snapshot = await ai_decision_policy_snapshot(session)
            audits = list(
                (
                    await session.scalars(
                        select(RuntimeConfigAuditRecord).where(
                            RuntimeConfigAuditRecord.category == "ai_decision"
                        )
                    )
                ).all()
            )

        assert snapshot.enabled is True
        assert snapshot.max_live_data_lag_seconds == 90
        assert snapshot.prior_decisions_limit == 18
        assert {item.target_key for item in audits} >= {
            "ai.max_live_data_lag_seconds",
            "ai.prior_decisions_limit",
        }

        with pytest.raises(ValueError, match="between 1 and 100"):
            await policy.set_setting(
                "ai.prior_decisions_limit",
                101,
                actor="dev@localhost",
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_global_ai_decision_switch_stops_runtime_provider_scheduling() -> None:
    engine, factory, config, policy = await _services()
    try:
        await config.ensure_seeded(actor="bootstrap")
        await policy.ensure_seeded(actor="bootstrap")

        async with factory() as session:
            before = await active_ai_experiments(session)
        assert [item[:2] for item in before] == [("openai", "runtime-policy-model")]

        await policy.set_setting(
            "ai.decisions.enabled",
            False,
            actor="dev@localhost",
        )
        async with factory() as session:
            assert await active_ai_experiments(session) == ()

        await policy.set_setting(
            "ai.decisions.enabled",
            True,
            actor="dev@localhost",
        )
        async with factory() as session:
            after = await active_ai_experiments(session)
        assert [item[:2] for item in after] == [("openai", "runtime-policy-model")]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_secret_status_reports_configuration_without_plaintext() -> None:
    engine, _factory, _config, policy = await _services()
    try:
        payload = await policy.secret_status_payload()
        serialized = json.dumps(payload)
        by_key = {item["key"]: item for item in payload["items"]}

        assert by_key["auth.google.client_secret"]["configured"] is True
        assert by_key["auth.google.client_secret"]["decryptable"] is True
        assert by_key["auth.google.client_secret"]["operational"] is True
        assert by_key["auth.google.client_secret"]["fallback_available"] is True
        assert by_key["auth.google.client_secret"]["storage"] == "BOOTSTRAP_FALLBACK"
        assert by_key["ai.openai.api_key"]["configured"] is True
        assert by_key["ai.openai.api_key"]["operational"] is True
        assert by_key["ai.openai.api_key"]["storage"] == "BOOTSTRAP_FALLBACK"
        assert by_key["ai.gemini.api_key"]["configured"] is False
        assert by_key["ai.gemini.api_key"]["operational"] is False
        assert "bootstrap-openai-key" not in serialized
        assert "bootstrap-google-secret" not in serialized
    finally:
        await engine.dispose()


class _FakePolicy:
    def __init__(self) -> None:
        self.flags = {
            "feature.performance.enabled": False,
            "feature.billing_checkout.enabled": False,
        }

    async def feature_enabled(self, key: str) -> bool:
        return self.flags.get(key, True)


@pytest.mark.asyncio
async def test_runtime_feature_middleware_hard_gates_surfaces_but_keeps_billing_maintenance() -> (
    None
):
    policy = _FakePolicy()
    app = FastAPI()
    app.add_middleware(RuntimeFeatureFlagMiddleware, policy=policy)

    @app.get("/api/review/ai-quality/benchmark")
    async def benchmark():
        return {"ok": True}

    @app.post("/api/billing/checkout/pro_monthly")
    async def checkout():
        return {"ok": True}

    @app.post("/api/billing/series/series-1/checkout")
    async def series_checkout():
        return {"ok": True}

    @app.get("/api/billing/account")
    async def account():
        return {"ok": True}

    @app.post("/api/billing/webhooks/paddle")
    async def webhook():
        return {"ok": True}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        review = await client.get("/api/review/ai-quality/benchmark")
        checkout_response = await client.post("/api/billing/checkout/pro_monthly")
        series_response = await client.post("/api/billing/series/series-1/checkout")
        account_response = await client.get("/api/billing/account")
        webhook_response = await client.post("/api/billing/webhooks/paddle")

    assert review.status_code == 503
    assert checkout_response.status_code == 503
    assert series_response.status_code == 503
    assert account_response.status_code == 200
    assert webhook_response.status_code == 200
