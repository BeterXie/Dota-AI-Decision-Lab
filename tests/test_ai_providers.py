import json

import httpx
import pytest

from app.ai.anthropic import AnthropicDecisionProvider
from app.ai.chat_completions import KimiDecisionProvider
from app.ai.deepseek import DeepSeekDecisionProvider
from app.ai.gemini import GeminiDecisionProvider
from app.ai.openai import OpenAiDecisionProvider

DECISION = {
    "action": "NO_BUY",
    "fair_probability_a": None,
    "confidence": 0.4,
    "market_assessment": "UNKNOWN",
    "minimum_acceptable_odds_a": None,
    "primary_reasons": ["Evidence is incomplete"],
    "counter_arguments": ["The market may already price known strength"],
    "data_quality_concerns": ["Historical sample is small"],
    "blockers": [],
}


@pytest.mark.asyncio
async def test_openai_uses_responses_strict_text_format() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "model": "gpt-5.6-terra",
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": json.dumps(DECISION)}],
                    }
                ],
            },
        )

    client = httpx.AsyncClient(
        base_url="https://api.openai.com/v1", transport=httpx.MockTransport(handler)
    )
    provider = OpenAiDecisionProvider(
        api_key="test",
        model="gpt-5.6-terra",
        base_url="https://api.openai.com/v1",
        reasoning_effort="xhigh",
        timeout_seconds=1,
        client=client,
    )

    result = await provider.decide('{"snapshot_hash":"same"}')

    assert result.decision.action == "NO_BUY"
    assert captured["text"]["format"]["type"] == "json_schema"
    assert captured["text"]["format"]["strict"] is True
    assert captured["reasoning"] == {"effort": "xhigh"}
    await client.aclose()


@pytest.mark.asyncio
async def test_anthropic_uses_output_config_format() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "model": "claude-sonnet-4-6",
                "stop_reason": "end_turn",
                "content": [{"type": "text", "text": json.dumps(DECISION)}],
            },
        )

    client = httpx.AsyncClient(
        base_url="https://api.anthropic.com/v1", transport=httpx.MockTransport(handler)
    )
    provider = AnthropicDecisionProvider(
        api_key="test",
        model="claude-sonnet-4-6",
        base_url="https://api.anthropic.com/v1",
        timeout_seconds=1,
        client=client,
    )

    result = await provider.decide('{"snapshot_hash":"same"}')

    assert result.decision.action == "NO_BUY"
    assert captured["output_config"]["format"]["type"] == "json_schema"
    await client.aclose()


@pytest.mark.asyncio
async def test_gemini_uses_interactions_response_format() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "model": "gemini-3.6-flash",
                "steps": [
                    {
                        "type": "model_output",
                        "content": [{"type": "text", "text": json.dumps(DECISION)}],
                    }
                ],
            },
        )

    client = httpx.AsyncClient(
        base_url="https://generativelanguage.googleapis.com/v1beta",
        transport=httpx.MockTransport(handler),
    )
    provider = GeminiDecisionProvider(
        api_key="test",
        model="gemini-3.6-flash",
        base_url="https://generativelanguage.googleapis.com/v1beta",
        timeout_seconds=1,
        client=client,
    )

    result = await provider.decide('{"snapshot_hash":"same"}')

    assert result.decision.action == "NO_BUY"
    assert captured["url"] == "https://generativelanguage.googleapis.com/v1beta/interactions"
    assert captured["response_format"][0]["mime_type"] == "application/json"
    assert captured["system_instruction"]
    assert captured["input"] == '{"snapshot_hash":"same"}'
    await client.aclose()


@pytest.mark.asyncio
async def test_deepseek_uses_responses_strict_text_format() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "model": "deepseek-v4-flash",
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": json.dumps(DECISION)}],
                    }
                ],
            },
        )

    base_url = "https://api.deepseek.com"
    client = httpx.AsyncClient(base_url=base_url, transport=httpx.MockTransport(handler))
    provider = DeepSeekDecisionProvider(
        api_key="test",
        model="deepseek-v4-flash",
        base_url=base_url,
        reasoning_effort="xhigh",
        timeout_seconds=1,
        client=client,
    )

    result = await provider.decide('{"snapshot_hash":"same"}')

    assert provider.name == "deepseek"
    assert result.decision.action == "NO_BUY"
    assert captured["url"] == f"{base_url}/responses"
    assert captured["text"]["format"]["type"] == "json_schema"
    assert captured["text"]["format"]["strict"] is True
    assert captured["reasoning"] == {"effort": "xhigh"}
    assert captured["input"] == '{"snapshot_hash":"same"}'
    await client.aclose()


@pytest.mark.asyncio
async def test_kimi_requests_and_validates_json_from_chat_completions() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "model": "kimi-k2.5",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": json.dumps(DECISION)},
                    }
                ],
            },
        )

    base_url = "https://api.moonshot.cn/v1"
    client = httpx.AsyncClient(base_url=base_url, transport=httpx.MockTransport(handler))
    provider = KimiDecisionProvider(
        api_key="test",
        model="kimi-k2.5",
        base_url=base_url,
        timeout_seconds=1,
        client=client,
    )

    result = await provider.decide('{"snapshot_hash":"same"}')

    assert result.decision.action == "NO_BUY"
    assert captured["url"] == f"{base_url}/chat/completions"
    assert captured["response_format"] == {"type": "json_object"}
    assert captured["thinking"] == {"type": "disabled"}
    assert captured["max_tokens"] == 4096
    assert captured["messages"][1]["content"] == '{"snapshot_hash":"same"}'
    assert "minimum_acceptable_odds_a" in captured["messages"][0]["content"]
    await client.aclose()
