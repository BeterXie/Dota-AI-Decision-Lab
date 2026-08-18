from __future__ import annotations

from urllib.parse import urlsplit

_CLOUD_PROVIDER_HOSTS: dict[str, frozenset[str]] = {
    "openai": frozenset({"api.openai.com"}),
    "anthropic": frozenset({"api.anthropic.com"}),
    "gemini": frozenset({"generativelanguage.googleapis.com"}),
    "deepseek": frozenset({"api.deepseek.com"}),
    "kimi": frozenset({"api.moonshot.cn"}),
}


def validate_provider_base_url(provider: str, base_url: str) -> str:
    """Validate a provider endpoint before a managed credential can reach it.

    Cloud credentials are intentionally pinned to the provider's official API
    host. ``local_openai`` is the escape hatch for loopback/LAN/custom OpenAI-
    compatible endpoints and therefore accepts either HTTP or HTTPS.
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

    allowed_hosts = _CLOUD_PROVIDER_HOSTS.get(provider_key)
    if allowed_hosts is None:
        raise ValueError(f"unsupported AI provider: {provider}")
    if parsed.scheme != "https":
        raise ValueError(f"{provider_key} base_url must use https")
    if parsed.hostname.lower() not in allowed_hosts:
        allowed = ", ".join(sorted(allowed_hosts))
        raise ValueError(f"{provider_key} base_url must use an approved provider host: {allowed}")
    return value


def provider_base_url_is_allowed(provider: str, base_url: str) -> bool:
    try:
        validate_provider_base_url(provider, base_url)
    except ValueError:
        return False
    return True
