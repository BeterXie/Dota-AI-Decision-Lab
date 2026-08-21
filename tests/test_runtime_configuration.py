import pytest
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.ai.base import ai_decision_lane_key
from app.auth.social import SocialAuthSettings
from app.config import Settings, get_settings
from app.db import Base
from app.runtime_config.models import AiProviderConfigRecord, RuntimeConfigAuditRecord
from app.runtime_config.service import (
    RuntimeConfigurationService,
    RuntimeControlSettings,
    active_ai_experiments,
    resolve_ai_provider,
)


async def _service(*, openai_key: str | None = "env-openai-key"):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    settings = Settings(
        _env_file=None,
        openai_api_key=SecretStr(openai_key) if openai_key else None,
        openai_model="baseline-model",
        openai_reasoning_effort="high",
        ai_timeout_seconds=50,
        auth_enabled=True,
    )
    social = SocialAuthSettings(
        _env_file=None,
        external_base_url="http://127.0.0.1:5173",
        google_enabled=False,
        steam_enabled=False,
    )
    service = RuntimeConfigurationService(
        factory,
        settings=settings,
        social_settings=social,
        bootstrap=RuntimeControlSettings(_env_file=None, admin_emails="dev@localhost"),
    )
    return engine, factory, service


@pytest.mark.asyncio
async def test_auth_switches_apply_without_recreating_service() -> None:
    engine, _factory, service = await _service()
    await service.ensure_seeded(actor="bootstrap")

    before = await service.auth_snapshot()
    assert before.email_enabled is True
    assert before.steam_available is False

    await service.set_setting(
        "auth.steam.enabled",
        True,
        actor="dev@localhost",
    )
    after = await service.auth_snapshot()
    assert after.steam_available is True
    assert after.provider_payload["steam"] is True

    await engine.dispose()


@pytest.mark.asyncio
async def test_ai_model_timeout_reasoning_and_enablement_are_hot(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "env-openai-key")
    get_settings.cache_clear()
    engine, factory, service = await _service()
    try:
        await service.ensure_seeded(actor="bootstrap")

        async with factory() as session:
            assert await active_ai_experiments(session) == (
                ai_decision_lane_key("openai", "baseline-model"),
            )

        payload = await service.upsert_ai_provider(
            "openai",
            "default",
            {
                "model": "challenger-model",
                "reasoning_effort": "medium",
                "timeout_seconds": 17,
                "enabled": True,
                "decisions_enabled": True,
            },
            actor="dev@localhost",
        )
        assert payload["model"] == "challenger-model"
        assert payload["reasoning_effort"] == "medium"
        assert payload["timeout_seconds"] == 17
        assert payload["secret_configured"] is True

        async with factory() as session:
            assert await active_ai_experiments(session) == (
                ai_decision_lane_key("openai", "challenger-model"),
            )
            provider = await resolve_ai_provider(
                session,
                "openai",
                "challenger-model",
                fallback=None,
            )
        assert provider.model == "challenger-model"
        assert provider.reasoning_effort == "medium"
        assert provider.runtime_timeout_seconds == 17
        await provider.close()

        await service.upsert_ai_provider(
            "openai",
            "default",
            {"enabled": False},
            actor="dev@localhost",
        )
        async with factory() as session:
            assert await active_ai_experiments(session) == ()
            with pytest.raises(ValueError, match="disabled or superseded"):
                await resolve_ai_provider(
                    session,
                    "openai",
                    "challenger-model",
                    fallback=None,
                )
    finally:
        await engine.dispose()
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_ai_key_can_be_configured_from_scratch_and_audit_never_contains_secret() -> None:
    sensitive_value = "highly-sensitive-provider-key"
    engine, factory, service = await _service(openai_key=sensitive_value)
    await service.ensure_seeded(actor="bootstrap")

    assert "ai.openai.api_key" in service.allowed_secret_keys
    await service.upsert_ai_provider(
        "openai",
        "default",
        {
            "model": "db-only-model",
            "enabled": True,
            "decisions_enabled": True,
        },
        actor="dev@localhost",
    )

    async with factory() as session:
        row = await session.scalar(
            select(AiProviderConfigRecord).where(AiProviderConfigRecord.provider == "openai")
        )
        assert row is not None and row.api_key_secret_key == "ai.openai.api_key"
        audits = list((await session.scalars(select(RuntimeConfigAuditRecord))).all())
    serialized_audit = str(
        [(item.previous_value, item.new_value, item.secret_changed) for item in audits]
    )
    assert audits
    assert sensitive_value not in serialized_audit

    await engine.dispose()
