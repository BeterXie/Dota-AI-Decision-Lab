from datetime import UTC, datetime

import pytest

from app.providers.liquipedia.fetch import FetchedPage, LiquipediaFetchChain


class FakeFetcher:
    def __init__(self, name: str, calls: list[str], *, fail: bool) -> None:
        self._name = name
        self._calls = calls
        self._fail = fail

    async def fetch(self, url: str) -> FetchedPage:
        self._calls.append(self._name)
        if self._fail:
            raise RuntimeError(f"{self._name} unavailable")
        now = datetime(2026, 8, 18, 4, 0, tzinfo=UTC)
        return FetchedPage(
            url=url,
            html="<html><body>ok</body></html>",
            request_started_at=now,
            received_at=now,
            transport=self._name,
        )

    async def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_liquipedia_fetch_chain_stops_at_first_success() -> None:
    calls: list[str] = []
    chain = LiquipediaFetchChain(
        (
            FakeFetcher("httpx", calls, fail=False),
            FakeFetcher("curl-cffi", calls, fail=False),
            FakeFetcher("crawlee-playwright", calls, fail=False),
        )
    )

    page = await chain.fetch("https://liquipedia.net/dota2/Liquipedia:Matches")

    assert page.transport == "httpx"
    assert calls == ["httpx"]


@pytest.mark.asyncio
async def test_liquipedia_fetch_chain_uses_curl_before_browser() -> None:
    calls: list[str] = []
    chain = LiquipediaFetchChain(
        (
            FakeFetcher("httpx", calls, fail=True),
            FakeFetcher("curl-cffi", calls, fail=False),
            FakeFetcher("crawlee-playwright", calls, fail=False),
        )
    )

    page = await chain.fetch("https://liquipedia.net/dota2/Liquipedia:Matches")

    assert page.transport == "curl-cffi"
    assert calls == ["httpx", "curl-cffi"]


@pytest.mark.asyncio
async def test_liquipedia_fetch_chain_uses_browser_only_as_last_fallback() -> None:
    calls: list[str] = []
    chain = LiquipediaFetchChain(
        (
            FakeFetcher("httpx", calls, fail=True),
            FakeFetcher("curl-cffi", calls, fail=True),
            FakeFetcher("crawlee-playwright", calls, fail=False),
        )
    )

    page = await chain.fetch("https://liquipedia.net/dota2/Liquipedia:Matches")

    assert page.transport == "crawlee-playwright"
    assert calls == ["httpx", "curl-cffi", "crawlee-playwright"]
