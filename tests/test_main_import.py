import pytest


def test_main_module_imports() -> None:
    from app import main

    assert callable(main.main)


@pytest.mark.asyncio
async def test_configured_deepseek_and_kimi_are_registered() -> None:
    from app.config import Settings
    from app.main import _ai_providers

    settings = Settings(
        _env_file=None,
        deepseek_api_key="deepseek-test",
        kimi_api_key="kimi-test",
    )
    providers = _ai_providers(settings)

    assert {provider.name for provider in providers} == {"deepseek", "kimi"}
    for provider in providers:
        await provider.close()
