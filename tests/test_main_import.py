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


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1"])
def test_loopback_dashboard_hosts_are_allowed(host: str) -> None:
    from app.config import Settings

    settings = Settings(_env_file=None, host=host, api_token="unused-future-token")

    assert settings.host == host


def test_api_token_does_not_unlock_non_loopback_binding() -> None:
    from app.config import Settings

    with pytest.raises(ValueError, match="HOST must be loopback"):
        Settings(
            _env_file=None,
            host="0.0.0.0",
            api_token="this-is-not-authentication",
        )


def test_runtime_host_cannot_be_reassigned_to_non_loopback() -> None:
    from app.config import Settings

    settings = Settings(_env_file=None, host="127.0.0.1")

    with pytest.raises(ValueError, match="HOST must be loopback"):
        settings.host = "0.0.0.0"


@pytest.mark.asyncio
async def test_configured_openai_deepseek_and_kimi_are_registered() -> None:
    from app.config import Settings
    from app.main import _ai_providers

    settings = Settings(
        _env_file=None,
        openai_api_key="openai-test",
        deepseek_api_key="deepseek-test",
        kimi_api_key="kimi-test",
        kimi_decisions_enabled=True,
    )
    providers = _ai_providers(settings)

    assert {provider.name for provider in providers} == {"openai", "deepseek", "kimi"}
    # deepseek flash decisions are disabled by default (flash still powers
    # email translation); only the pro model votes.
    assert [provider.model for provider in providers] == [
        "gpt-5.6-terra",
        "deepseek-v4-pro",
        "kimi-k2.5",
    ]
    assert [
        provider.reasoning_effort
        for provider in providers
        if provider.name in {"openai", "deepseek"}
    ] == ["high", "high"]
    for provider in providers:
        await provider.close()


@pytest.mark.asyncio
async def test_kimi_is_excluded_when_decisions_are_disabled() -> None:
    from app.config import Settings
    from app.main import _ai_providers

    settings = Settings(
        _env_file=None,
        openai_api_key="openai-test",
        kimi_api_key="kimi-test",
        kimi_decisions_enabled=False,
    )
    providers = _ai_providers(settings)

    assert {provider.name for provider in providers} == {"openai"}
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
