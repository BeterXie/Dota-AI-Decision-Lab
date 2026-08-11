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
