import pytest


def test_main_module_imports() -> None:
    from app import main

    assert callable(main.main)


def test_ai_checkpoints_start_at_ten_minutes_by_default() -> None:
    from app.config import Settings

    settings = Settings(_env_file=None)

    assert settings.ai_min_game_time_seconds == 600
    assert settings.checkpoint_minutes[0] == 10
    assert 5 not in settings.checkpoint_minutes


@pytest.mark.asyncio
async def test_configured_openai_deepseek_and_kimi_are_registered() -> None:
    from app.config import Settings
    from app.main import _ai_providers

    settings = Settings(
        _env_file=None,
        openai_api_key="openai-test",
        deepseek_api_key="deepseek-test",
        kimi_api_key="kimi-test",
    )
    providers = _ai_providers(settings)

    assert {provider.name for provider in providers} == {"openai", "deepseek", "kimi"}
    assert [provider.model for provider in providers] == [
        "gpt-5.6-terra",
        "deepseek-v4-flash",
        "deepseek-v4-pro",
        "kimi-k2.5",
    ]
    assert [
        provider.reasoning_effort
        for provider in providers
        if provider.name in {"openai", "deepseek"}
    ] == ["xhigh", "xhigh", "xhigh"]
    for provider in providers:
        await provider.close()


@pytest.mark.asyncio
async def test_email_readiness_distinguishes_disabled_missing_and_configured() -> None:
    from app.config import Settings
    from app.main import _initialize_dependency_health
    from app.runtime.health import HealthRegistry

    disabled = HealthRegistry()
    await _initialize_dependency_health(
        disabled,
        settings=Settings(_env_file=None),
        ai_provider_names=(),
    )
    assert (await disabled.snapshot())["dependencies"]["EMAIL"]["status"] == "DISABLED"

    missing = HealthRegistry()
    await _initialize_dependency_health(
        missing,
        settings=Settings(_env_file=None, email_notifications_enabled=True),
        ai_provider_names=(),
    )
    missing_email = (await missing.snapshot())["dependencies"]["EMAIL"]
    assert missing_email["status"] == "ACTION_REQUIRED"
    assert "RESEND_API_KEY" in missing_email["message"]
    assert "RESEND_FROM" in missing_email["message"]

    configured = HealthRegistry()
    await _initialize_dependency_health(
        configured,
        settings=Settings(
            _env_file=None,
            email_notifications_enabled=True,
            email_recipients="one@example.com,two@example.com",
            resend_api_key="resend-test-key",
            resend_from="Decision Lab <alerts@example.com>",
        ),
        ai_provider_names=(),
    )
    configured_email = (await configured.snapshot())["dependencies"]["EMAIL"]
    assert configured_email["status"] == "UNKNOWN"
    assert configured_email["metadata"]["recipient_count"] == 2
