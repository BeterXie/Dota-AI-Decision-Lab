import json

import httpx
import pytest

from app.providers.stratz.client import StratzClient


@pytest.mark.asyncio
async def test_stratz_posts_to_exact_graphql_endpoint() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers.get("Authorization")
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json={"data": {"__typename": "Query"}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = StratzClient(
        "https://api.stratz.com/graphql",
        "fixture-token",
        client=client,
    )

    result = await provider.execute(
        operation_name="CredentialProbe",
        query="query CredentialProbe { __typename }",
        variables={},
    )

    assert captured["url"] == "https://api.stratz.com/graphql"
    assert result.payload == {"data": {"__typename": "Query"}}
    await client.aclose()


@pytest.mark.asyncio
async def test_stratz_client_serializes_requests_through_rate_limit_gate() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"data": {"__typename": "Query"}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = StratzClient("https://api.stratz.com/graphql", "fixture-token", client=client)
    await provider.execute(operation_name="A", query="query A { __typename }", variables={})
    await provider.execute(operation_name="B", query="query B { __typename }", variables={})
    assert calls == 2
    await client.aclose()


@pytest.mark.asyncio
async def test_owned_stratz_client_rebuilds_poisoned_pool_once(monkeypatch) -> None:
    request = httpx.Request("POST", "https://api.stratz.com/graphql")

    class FakeClient:
        def __init__(self, *, fails: bool) -> None:
            self.fails = fails
            self.closed = False
            self.calls = 0

        async def post(self, _url: str, *, json: dict) -> httpx.Response:
            self.calls += 1
            assert json["operationName"] == "PoolRecovery"
            if self.fails:
                raise httpx.PoolTimeout("poisoned pool", request=request)
            return httpx.Response(
                200,
                json={"data": {"__typename": "Query"}},
                request=request,
            )

        async def aclose(self) -> None:
            self.closed = True

    clients = [FakeClient(fails=True), FakeClient(fails=False)]

    def client_factory(**_kwargs) -> FakeClient:
        return clients.pop(0)

    monkeypatch.setattr(httpx, "AsyncClient", client_factory)
    provider = StratzClient("https://api.stratz.com/graphql", "fixture-token")
    poisoned = provider._client

    result = await provider.execute(
        operation_name="PoolRecovery",
        query="query PoolRecovery { __typename }",
        variables={},
    )

    assert result.payload == {"data": {"__typename": "Query"}}
    assert poisoned.closed is True
    assert provider._client.calls == 1
    await provider.close()
    assert provider._client.closed is True
