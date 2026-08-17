from urllib.parse import parse_qs, urlsplit

import pytest
from pydantic import SecretStr

from app.auth.social import (
    SocialAuthProviderError,
    SocialAuthService,
    SocialAuthSettings,
    _steam_id_from_claimed_id,
)


def test_google_authorization_url_keeps_secret_server_side() -> None:
    settings = SocialAuthSettings(
        _env_file=None,
        external_base_url="http://127.0.0.1:5173",
        google_enabled=True,
        google_client_id="client-id.apps.googleusercontent.com",
        google_client_secret=SecretStr("server-secret"),
    )
    url = SocialAuthService(settings).google_authorization_url("state-token")
    parsed = urlsplit(url)
    query = parse_qs(parsed.query)

    assert parsed.netloc == "accounts.google.com"
    assert query["client_id"] == ["client-id.apps.googleusercontent.com"]
    assert query["state"] == ["state-token"]
    assert query["redirect_uri"] == ["http://127.0.0.1:5173/api/auth/google/callback"]
    assert query["scope"] == ["openid email profile"]
    assert "server-secret" not in url


def test_steam_authorization_url_uses_openid_and_binds_state_to_return_url() -> None:
    settings = SocialAuthSettings(
        _env_file=None,
        external_base_url="http://127.0.0.1:5173",
        steam_enabled=True,
    )
    url = SocialAuthService(settings).steam_authorization_url("steam-state")
    query = parse_qs(urlsplit(url).query)

    assert query["openid.mode"] == ["checkid_setup"]
    assert query["openid.realm"] == ["http://127.0.0.1:5173/"]
    return_to = urlsplit(query["openid.return_to"][0])
    assert return_to.path == "/api/auth/steam/callback"
    assert parse_qs(return_to.query)["state"] == ["steam-state"]


def test_public_plain_http_origin_does_not_enable_social_login() -> None:
    settings = SocialAuthSettings(
        _env_file=None,
        external_base_url="http://example.com",
        steam_enabled=True,
        google_enabled=True,
        google_client_id="client",
        google_client_secret=SecretStr("secret"),
    )

    assert settings.steam_available is False
    assert settings.google_available is False


def test_steam_claimed_id_is_reduced_to_stable_steam_id() -> None:
    steam_id = "76561198000000000"
    assert _steam_id_from_claimed_id(f"https://steamcommunity.com/openid/id/{steam_id}") == steam_id
    with pytest.raises(SocialAuthProviderError):
        _steam_id_from_claimed_id("https://example.com/not-steam")
