from datetime import UTC, datetime

import pytest

from app.providers.liquipedia.fetch import (
    LIQUIPEDIA_PARSE_INTERVAL_SECONDS,
    FetchedApiResponse,
    LiquipediaMediaWikiClient,
)


class FakeTransport:
    def __init__(self, name: str, calls: list[str], *, fail: bool) -> None:
        self._name = name
        self._calls = calls
        self._fail = fail

    async def get_json(self, url: str, *, params: dict[str, str], headers: dict[str, str]):
        self._calls.append(self._name)
        assert url.endswith("/dota2/api.php")
        assert params["action"] == "parse"
        assert headers["Accept-Encoding"] == "gzip"
        assert "Dota-AI-Decision-Lab" in headers["User-Agent"]
        if self._fail:
            raise RuntimeError(f"{self._name} unavailable")
        now = datetime(2026, 8, 18, 4, 0, tzinfo=UTC)
        return FetchedApiResponse(
            payload={
                "parse": {
                    "title": params["page"],
                    "revid": 123,
                    "displaytitle": "Tournament directory",
                    "text": "<ul class='tournaments-list'></ul>",
                }
            },
            request_started_at=now,
            received_at=now,
            transport=self._name,
        )

    async def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_liquipedia_mediawiki_client_stops_at_httpx_success() -> None:
    calls: list[str] = []
    client = LiquipediaMediaWikiClient(
        (
            FakeTransport("httpx", calls, fail=False),
            FakeTransport("curl-cffi", calls, fail=False),
        ),
        parse_interval_seconds=0,
    )

    page = await client.parse_page("Liquipedia:Tournaments")

    assert page.transport == "httpx"
    assert page.page_name == "Liquipedia:Tournaments"
    assert page.revision_id == 123
    assert calls == ["httpx"]


@pytest.mark.asyncio
async def test_liquipedia_mediawiki_client_uses_curl_only_as_api_transport_fallback() -> None:
    calls: list[str] = []
    client = LiquipediaMediaWikiClient(
        (
            FakeTransport("httpx", calls, fail=True),
            FakeTransport("curl-cffi", calls, fail=False),
        ),
        parse_interval_seconds=0,
    )

    page = await client.parse_page("Liquipedia:Matches")

    assert page.transport == "curl-cffi"
    assert calls == ["httpx", "curl-cffi"]


def test_liquipedia_parse_default_respects_published_30_second_limit() -> None:
    assert LIQUIPEDIA_PARSE_INTERVAL_SECONDS >= 30.0
