from app.config import Settings


def test_paddle_billing_is_optional_and_sandbox_by_default() -> None:
    settings = Settings(_env_file=None, paddle_enabled=False)
    assert settings.paddle_configuration_errors == ()
    assert settings.paddle_environment == "sandbox"
    assert settings.paddle_api_base_url == "https://sandbox-api.paddle.com"


def test_enabled_paddle_requires_auth_secrets_and_catalog_price() -> None:
    incomplete = Settings(_env_file=None, paddle_enabled=True)
    assert incomplete.paddle_configuration_errors == (
        "AUTH_ENABLED=true",
        "PADDLE_API_KEY",
        "PADDLE_WEBHOOK_SECRET",
        "PADDLE_PRO_*_PRICE_ID",
    )

    configured = Settings(
        _env_file=None,
        auth_enabled=True,
        paddle_enabled=True,
        paddle_api_key="pdl_sdbx_apikey_test",
        paddle_webhook_secret="pdl_ntfset_test",
        paddle_pro_monthly_price_id="pri_monthly",
    )
    assert configured.paddle_configuration_errors == ()


def test_live_paddle_uses_live_api_endpoint() -> None:
    settings = Settings(_env_file=None, paddle_environment="live")
    assert settings.paddle_api_base_url == "https://api.paddle.com"
