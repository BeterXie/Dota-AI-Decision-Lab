from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

import httpx
from curl_cffi.requests import AsyncSession

from app.providers.common import create_system_ssl_context


DEFAULT_USER_AGENT = "Dota-AI-Decision-Lab/0.1.0"


@dataclass(frozen=True, slots=True)
class FetchedPage:
    url: str
    html: str
    request_started_at: datetime
    received_at: datetime
    transport: str


class PageFetcher(Protocol):
    async def fetch(self, url: str) -> FetchedPage: ...

    async def close(self) -> None: ...


class HttpxLiquipediaFetcher:
    def __init__(
        self,
        *,
        timeout_seconds: float = 15.0,
        user_agent: str = DEFAULT_USER_AGENT,
    ) -> None:
        self._client = httpx.AsyncClient(
            timeout=timeout_seconds,
            verify=create_system_ssl_context(),
            follow_redirects=True,
            headers={
                "Accept": "text/html,application/xhtml+xml",
                "User-Agent": user_agent,
            },
        )

    async def fetch(self, url: str) -> FetchedPage:
        started = datetime.now(UTC)
        response = await self._client.get(url)
        received = datetime.now(UTC)
        response.raise_for_status()
        _require_html(response.headers.get("content-type", ""))
        return FetchedPage(
            url=str(response.url),
            html=response.text,
            request_started_at=started,
            received_at=received,
            transport="httpx",
        )

    async def close(self) -> None:
        await self._client.aclose()


class CurlLiquipediaFetcher:
    def __init__(
        self,
        *,
        timeout_seconds: float = 15.0,
        user_agent: str = DEFAULT_USER_AGENT,
    ) -> None:
        self._timeout_seconds = timeout_seconds
        self._user_agent = user_agent
        self._session = AsyncSession()

    async def fetch(self, url: str) -> FetchedPage:
        started = datetime.now(UTC)
        response = await self._session.get(
            url,
            timeout=self._timeout_seconds,
            allow_redirects=True,
            impersonate="chrome",
            headers={
                "Accept": "text/html,application/xhtml+xml",
                "User-Agent": self._user_agent,
            },
        )
        received = datetime.now(UTC)
        response.raise_for_status()
        _require_html(response.headers.get("content-type", ""))
        return FetchedPage(
            url=str(response.url),
            html=response.text,
            request_started_at=started,
            received_at=received,
            transport="curl-cffi",
        )

    async def close(self) -> None:
        await self._session.close()


class CrawleePlaywrightFetcher:
    """Browser fallback for pages that cannot be collected through HTTP.

    Crawlee is imported lazily so the core runtime can still import the provider
    in environments where the crawler worker has not installed its browser
    dependencies yet. Production crawler workers must install
    ``crawlee[playwright]`` and the Chromium browser binary before enabling this
    fallback.
    """

    async def fetch(self, url: str) -> FetchedPage:
        try:
            from crawlee.crawlers import PlaywrightCrawler
        except ImportError as exc:
            raise RuntimeError(
                "Liquipedia browser fallback requires crawlee[playwright]"
            ) from exc

        captured: list[tuple[str, str]] = []
        started = datetime.now(UTC)
        crawler = PlaywrightCrawler(max_requests_per_crawl=1)

        @crawler.router.default_handler
        async def handler(context) -> None:
            captured.append((context.request.url, await context.page.content()))

        await crawler.run([url])
        received = datetime.now(UTC)
        if not captured:
            raise RuntimeError("Crawlee Playwright fallback returned no page")
        final_url, html = captured[-1]
        return FetchedPage(
            url=final_url,
            html=html,
            request_started_at=started,
            received_at=received,
            transport="crawlee-playwright",
        )

    async def close(self) -> None:
        return None


class LiquipediaFetchChain:
    """Fetch Liquipedia with one deliberate escalation path.

    Fast HTTP is always attempted first, browser-impersonating curl second, and
    a real browser only as the final fallback. This keeps routine discovery
    cheap while preserving a deterministic escape hatch for JavaScript pages.
    """

    def __init__(self, fetchers: tuple[PageFetcher, ...]) -> None:
        if not fetchers:
            raise ValueError("Liquipedia fetch chain requires at least one fetcher")
        self._fetchers = fetchers

    @classmethod
    def default(cls) -> LiquipediaFetchChain:
        return cls(
            (
                HttpxLiquipediaFetcher(),
                CurlLiquipediaFetcher(),
                CrawleePlaywrightFetcher(),
            )
        )

    async def fetch(self, url: str) -> FetchedPage:
        failures: list[str] = []
        for fetcher in self._fetchers:
            try:
                return await fetcher.fetch(url)
            except Exception as exc:
                failures.append(f"{type(exc).__name__}: {exc}")
        raise RuntimeError("Liquipedia fetch chain failed: " + "; ".join(failures))

    async def close(self) -> None:
        for fetcher in self._fetchers:
            await fetcher.close()


def _require_html(content_type: str) -> None:
    if "text/html" not in content_type and "application/xhtml+xml" not in content_type:
        raise ValueError("Liquipedia response is not HTML")
