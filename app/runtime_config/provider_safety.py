from __future__ import annotations

from urllib.parse import urlsplit

_CLOUD_PROVIDERS = frozenset({"openai", "anthropic", "gemini", "deepseek", "kimi"})


def validate_provider_base_url(provider: str, base_url: str) -> str:
    """Validate a provider endpoint before a managed credential can reach it.

    Cloud providers may use their official endpoint or an operator-selected
    HTTPS relay. ``local_openai`` additionally accepts HTTP for loopback/LAN
    OpenAI-compatible endpoints.
    """

    value = base_url.strip().rstrip("/")
    if not value:
        raise ValueError("base_url must be a non-empty URL")
    parsed = urlsplit(value)
    if parsed.username or parsed.password:
        raise ValueError("base_url must not contain user credentials")
    if parsed.query or parsed.fragment:
        raise ValueError("base_url must not contain a query string or fragment")
    if not parsed.hostname:
        raise ValueError("base_url must include a hostname")

    provider_key = provider.strip().lower()
    if provider_key == "local_openai":
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("local_openai base_url must use http or https")
        return value

    if provider_key not in _CLOUD_PROVIDERS:
        raise ValueError(f"unsupported AI provider: {provider}")
    if parsed.scheme != "https":
        raise ValueError(f"{provider_key} base_url must use https")
    return value


def provider_base_url_is_allowed(provider: str, base_url: str) -> bool:
    try:
        validate_provider_base_url(provider, base_url)
    except ValueError:
        return False
    return True
