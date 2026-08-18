from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from time import monotonic
from typing import Any, Protocol
from urllib.parse import quote

import httpx
from curl_cffi.requests import AsyncSession

from app.providers.common import create_system_ssl_context

LIQUIPEDIA_MEDIAWIKI_API_URL = "https://liquipedia.net/dota2/api.php"
LIQUIPEDIA_PARSE_INTERVAL_SECONDS = 30.0
DEFAULT_USER_AGENT = "Dota-AI-Decision-Lab/0.1.0 (https://github.com/BeterXie/Dota-AI-Decision-Lab)"


@dataclass(frozen=True, slots=True)
class FetchedApiResponse:
    payload: dict[str, Any]
    request_started_at: datetime
    received_at: datetime
    transport: str


@dataclass(frozen=True, slots=True)
class FetchedPage:
    page_name: str
    display_title: str
    revision_id: int | None
    source_url: str
    html: str
    request_started_at: datetime
    received_at: datetime
    transport: str


class ApiTransport(Protocol):
    async def get_json(
        self,
        url: str,
        *,
        params: dict[str, str],
        headers: dict[str, str],
    ) -> FetchedApiResponse: ...

    async def close(self) -> None: ...


class HttpxLiquipediaApiTransport:
    def __init__(self, *, timeout_seconds: float = 15.0) -> None:
        self._client = httpx.AsyncClient(
            timeout=timeout_seconds,
            verify=create_system_ssl_context(),
            follow_redirects=True,
        )

    async def get_json(
        self,
        url: str,
        *,
        params: dict[str, str],
        headers: dict[str, str],
    ) -> FetchedApiResponse:
        started = datetime.now(UTC)
        response = await self._client.get(url, params=params, headers=headers)
        received = datetime.now(UTC)
        response.raise_for_status()
        if "application/json" not in response.headers.get("content-type", ""):
            raise ValueError("Liquipedia MediaWiki API response is not JSON")
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Liquipedia MediaWiki API response must be an object")
        return FetchedApiResponse(payload, started, received, "httpx")

    async def close(self) -> None:
        await self._client.aclose()


class CurlLiquipediaApiTransport:
    """HTTP fallback that still talks only to Liquipedia's permitted API endpoint."""

    def __init__(self, *, timeout_seconds: float = 15.0) -> None:
        self._timeout_seconds = timeout_seconds
        self._session = AsyncSession()

    async def get_json(
        self,
        url: str,
        *,
        params: dict[str, str],
        headers: dict[str, str],
    ) -> FetchedApiResponse:
        started = datetime.now(UTC)
        response = await self._session.get(
            url,
            params=params,
            headers=headers,
            timeout=self._timeout_seconds,
            allow_redirects=True,
        )
        received = datetime.now(UTC)
        response.raise_for_status()
        if "application/json" not in response.headers.get("content-type", ""):
            raise ValueError("Liquipedia MediaWiki API curl response is not JSON")
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Liquipedia MediaWiki API curl response must be an object")
        return FetchedApiResponse(payload, started, received, "curl-cffi")

    async def close(self) -> None:
        await self._session.close()


class LiquipediaMediaWikiClient:
    """Rate-limited, cache-friendly access to Liquipedia's MediaWiki API.

    Liquipedia currently forbids automated access to generated HTML pages. The
    provider therefore uses ``action=parse`` to obtain rendered page HTML from
    the allowed API. Browser automation is deliberately not used to bypass that
    policy.
    """

    def __init__(
        self,
        transports: tuple[ApiTransport, ...] | None = None,
        *,
        api_url: str = LIQUIPEDIA_MEDIAWIKI_API_URL,
        user_agent: str = DEFAULT_USER_AGENT,
        parse_interval_seconds: float = LIQUIPEDIA_PARSE_INTERVAL_SECONDS,
    ) -> None:
        if parse_interval_seconds < 0:
            raise ValueError("parse_interval_seconds must be non-negative")
        self._transports = transports or (
            HttpxLiquipediaApiTransport(),
            CurlLiquipediaApiTransport(),
        )
        if not self._transports:
            raise ValueError("Liquipedia MediaWiki client requires a transport")
        self._api_url = api_url
        self._user_agent = user_agent
        self._parse_interval_seconds = parse_interval_seconds
        self._parse_lock = asyncio.Lock()
        self._next_parse_monotonic = 0.0

    async def parse_page(self, page_name: str) -> FetchedPage:
        normalized_page = page_name.strip()
        if not normalized_page:
            raise ValueError("page_name must not be empty")
        async with self._parse_lock:
            delay = self._next_parse_monotonic - monotonic()
            if delay > 0:
                await asyncio.sleep(delay)
            response = await self._request_parse(normalized_page)
            self._next_parse_monotonic = monotonic() + self._parse_interval_seconds
        return _parsed_page(normalized_page, response)

    async def close(self) -> None:
        for transport in self._transports:
            await transport.close()

    async def _request_parse(self, page_name: str) -> FetchedApiResponse:
        params = {
            "action": "parse",
            "page": page_name,
            "prop": "text|revid|displaytitle",
            "format": "json",
            "formatversion": "2",
            "redirects": "1",
        }
        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "User-Agent": self._user_agent,
        }
        failures: list[str] = []
        for transport in self._transports:
            try:
                return await transport.get_json(self._api_url, params=params, headers=headers)
            except Exception as exc:
                failures.append(f"{type(exc).__name__}: {exc}")
        raise RuntimeError("Liquipedia MediaWiki transports failed: " + "; ".join(failures))


def _parsed_page(page_name: str, response: FetchedApiResponse) -> FetchedPage:
    error = response.payload.get("error")
    if isinstance(error, dict):
        code = error.get("code", "unknown")
        raise ValueError(f"Liquipedia MediaWiki API error: {code}")
    parsed = response.payload.get("parse")
    if not isinstance(parsed, dict):
        raise ValueError("Liquipedia MediaWiki API response has no parse object")
    html = parsed.get("text")
    if not isinstance(html, str) or not html.strip():
        raise ValueError("Liquipedia MediaWiki parse response has no rendered HTML")
    display_title = parsed.get("displaytitle")
    if not isinstance(display_title, str):
        display_title = page_name
    revision_id = parsed.get("revid")
    if not isinstance(revision_id, int):
        revision_id = None
    return FetchedPage(
        page_name=page_name,
        display_title=display_title,
        revision_id=revision_id,
        source_url=_source_url(page_name),
        html=html,
        request_started_at=response.request_started_at,
        received_at=response.received_at,
        transport=response.transport,
    )


def _source_url(page_name: str) -> str:
    encoded = quote(page_name.replace(" ", "_"), safe="/:()")
    return f"https://liquipedia.net/dota2/{encoded}"
