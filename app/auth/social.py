from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

import httpx
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

_GOOGLE_AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
_GOOGLE_USERINFO_ENDPOINT = "https://openidconnect.googleapis.com/v1/userinfo"
_STEAM_OPENID_ENDPOINT = "https://steamcommunity.com/openid/login"
_OPENID_NS = "http://specs.openid.net/auth/2.0"
_OPENID_IDENTIFIER_SELECT = "http://specs.openid.net/auth/2.0/identifier_select"


class SocialAuthSettings(BaseSettings):
    """Provider credentials kept separate from the core runtime .env for now.

    `.env.social` is intentionally optional. Production deployments can provide
    the same `DOTA_AUTH_*` names as process environment variables.
    """

    model_config = SettingsConfigDict(
        env_file=".env.social",
        env_prefix="DOTA_AUTH_",
        extra="ignore",
    )

    external_base_url: str | None = None
    google_enabled: bool = False
    google_client_id: str | None = None
    google_client_secret: SecretStr | None = None
    steam_enabled: bool = False
    timeout_seconds: float = Field(default=15.0, gt=0, le=60)

    @property
    def google_available(self) -> bool:
        return bool(
            self.google_enabled
            and self.external_base_url
            and self.google_client_id
            and self.google_client_secret is not None
            and _safe_external_base_url(self.external_base_url)
        )

    @property
    def steam_available(self) -> bool:
        return bool(
            self.steam_enabled
            and self.external_base_url
            and _safe_external_base_url(self.external_base_url)
        )

    @property
    def provider_payload(self) -> dict[str, bool]:
        return {
            "email": True,
            "google": self.google_available,
            "steam": self.steam_available,
        }


@dataclass(frozen=True, slots=True)
class ExternalIdentityClaim:
    provider: str
    subject: str
    email: str | None = None
    email_verified: bool = False
    display_name: str | None = None
    avatar_url: str | None = None


class SocialAuthProviderError(RuntimeError):
    pass


class SocialAuthService:
    def __init__(self, settings: SocialAuthSettings) -> None:
        self.settings = settings

    def callback_url(self, provider: str) -> str:
        base = _required_base_url(self.settings.external_base_url)
        return f"{base}/api/auth/{provider}/callback"

    def google_authorization_url(self, state: str) -> str:
        if not self.settings.google_available:
            raise SocialAuthProviderError("Google login is not configured")
        params = {
            "client_id": self.settings.google_client_id or "",
            "redirect_uri": self.callback_url("google"),
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "prompt": "select_account",
        }
        return f"{_GOOGLE_AUTHORIZATION_ENDPOINT}?{urlencode(params)}"

    async def google_identity(self, code: str) -> ExternalIdentityClaim:
        if not self.settings.google_available or self.settings.google_client_secret is None:
            raise SocialAuthProviderError("Google login is not configured")
        async with httpx.AsyncClient(
            timeout=self.settings.timeout_seconds,
            follow_redirects=False,
        ) as client:
            token_response = await client.post(
                _GOOGLE_TOKEN_ENDPOINT,
                data={
                    "code": code,
                    "client_id": self.settings.google_client_id or "",
                    "client_secret": self.settings.google_client_secret.get_secret_value(),
                    "redirect_uri": self.callback_url("google"),
                    "grant_type": "authorization_code",
                },
                headers={"Accept": "application/json"},
            )
            if token_response.status_code >= 400:
                raise SocialAuthProviderError("Google rejected the authorization code")
            token_payload = token_response.json()
            access_token = token_payload.get("access_token")
            if not isinstance(access_token, str) or not access_token:
                raise SocialAuthProviderError(
                    "Google token response did not include an access token"
                )

            profile_response = await client.get(
                _GOOGLE_USERINFO_ENDPOINT,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/json",
                },
            )
        if profile_response.status_code >= 400:
            raise SocialAuthProviderError("Google profile lookup failed")
        profile = profile_response.json()
        subject = profile.get("sub")
        if not isinstance(subject, str) or not subject:
            raise SocialAuthProviderError("Google profile is missing its stable subject")
        return ExternalIdentityClaim(
            provider="google",
            subject=subject,
            email=_optional_string(profile.get("email")),
            email_verified=profile.get("email_verified") is True,
            display_name=_optional_string(profile.get("name")),
            avatar_url=_https_url(profile.get("picture")),
        )

    def steam_authorization_url(self, state: str) -> str:
        if not self.settings.steam_available:
            raise SocialAuthProviderError("Steam login is not configured")
        return_to = _with_query(self.callback_url("steam"), {"state": state})
        realm = f"{_required_base_url(self.settings.external_base_url)}/"
        params = {
            "openid.ns": _OPENID_NS,
            "openid.mode": "checkid_setup",
            "openid.return_to": return_to,
            "openid.realm": realm,
            "openid.identity": _OPENID_IDENTIFIER_SELECT,
            "openid.claimed_id": _OPENID_IDENTIFIER_SELECT,
        }
        return f"{_STEAM_OPENID_ENDPOINT}?{urlencode(params)}"

    async def steam_identity(
        self, params: dict[str, str], expected_state: str
    ) -> ExternalIdentityClaim:
        if not self.settings.steam_available:
            raise SocialAuthProviderError("Steam login is not configured")
        if params.get("openid.ns") != _OPENID_NS:
            raise SocialAuthProviderError("Steam OpenID namespace is invalid")
        if params.get("openid.op_endpoint") != _STEAM_OPENID_ENDPOINT:
            raise SocialAuthProviderError("Steam OpenID endpoint is invalid")

        claimed_id = params.get("openid.claimed_id", "")
        identity = params.get("openid.identity", "")
        if identity != claimed_id:
            raise SocialAuthProviderError("Steam OpenID identity mismatch")
        steam_id = _steam_id_from_claimed_id(claimed_id)

        return_to = params.get("openid.return_to", "")
        parsed_return = urlsplit(return_to)
        expected_callback = urlsplit(self.callback_url("steam"))
        if (
            parsed_return.scheme != expected_callback.scheme
            or parsed_return.netloc != expected_callback.netloc
            or parsed_return.path != expected_callback.path
        ):
            raise SocialAuthProviderError("Steam OpenID return URL is invalid")
        state_values = parse_qs(parsed_return.query).get("state", [])
        if state_values != [expected_state]:
            raise SocialAuthProviderError("Steam OpenID state mismatch")

        verification_payload = {
            key: value for key, value in params.items() if key.startswith("openid.")
        }
        verification_payload["openid.mode"] = "check_authentication"
        async with httpx.AsyncClient(
            timeout=self.settings.timeout_seconds,
            follow_redirects=False,
        ) as client:
            verify_response = await client.post(
                _STEAM_OPENID_ENDPOINT,
                data=verification_payload,
                headers={"Accept": "text/plain"},
            )
        if verify_response.status_code >= 400:
            raise SocialAuthProviderError("Steam OpenID verification failed")
        verdict = dict(
            line.split(":", 1) for line in verify_response.text.splitlines() if ":" in line
        )
        if verdict.get("is_valid") != "true":
            raise SocialAuthProviderError("Steam OpenID assertion is not valid")

        return ExternalIdentityClaim(
            provider="steam",
            subject=steam_id,
            display_name=f"Steam {steam_id[-6:]}",
        )


def _required_base_url(value: str | None) -> str:
    if value is None:
        raise SocialAuthProviderError("external auth base URL is not configured")
    cleaned = value.strip().rstrip("/")
    if not _safe_external_base_url(cleaned):
        raise SocialAuthProviderError("external auth base URL must be HTTPS or loopback HTTP")
    return cleaned


def _safe_external_base_url(value: str) -> bool:
    try:
        parsed = urlsplit(value.strip().rstrip("/"))
    except ValueError:
        return False
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        return False
    if parsed.path not in {"", "/"}:
        return False
    if parsed.scheme == "https" and parsed.hostname:
        return True
    return parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}


def _with_query(url: str, params: dict[str, str]) -> str:
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(params), ""))


def _steam_id_from_claimed_id(value: str) -> str:
    prefix = "https://steamcommunity.com/openid/id/"
    http_prefix = "http://steamcommunity.com/openid/id/"
    if value.startswith(prefix):
        steam_id = value[len(prefix) :]
    elif value.startswith(http_prefix):
        steam_id = value[len(http_prefix) :]
    else:
        raise SocialAuthProviderError("Steam claimed identity is invalid")
    if not steam_id.isdigit() or len(steam_id) < 16 or len(steam_id) > 20:
        raise SocialAuthProviderError("Steam ID is invalid")
    return steam_id


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _https_url(value: object) -> str | None:
    text = _optional_string(value)
    return text if text is not None and text.startswith("https://") else None
