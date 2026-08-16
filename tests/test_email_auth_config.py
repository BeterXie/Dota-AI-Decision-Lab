from app.config import Settings


def test_email_auth_configuration_is_optional_while_disabled() -> None:
    settings = Settings(_env_file=None, auth_enabled=False)
    assert settings.auth_configuration_errors == ()


def test_email_auth_configuration_requires_sender_and_strong_secret() -> None:
    incomplete = Settings(_env_file=None, auth_enabled=True)
    assert incomplete.auth_configuration_errors == (
        "RESEND_API_KEY",
        "RESEND_FROM",
        "AUTH_SECRET_KEY",
    )

    weak = Settings(
        _env_file=None,
        auth_enabled=True,
        resend_api_key="re_test",
        resend_from="Decision Lab <login@example.com>",
        auth_secret_key="too-short",
    )
    assert weak.auth_configuration_errors == ("AUTH_SECRET_KEY>=32_BYTES",)

    configured = Settings(
        _env_file=None,
        auth_enabled=True,
        resend_api_key="re_test",
        resend_from="Decision Lab <login@example.com>",
        auth_secret_key="0123456789abcdef0123456789abcdef",
    )
    assert configured.auth_configuration_errors == ()
