from typing import Any

import httpx

from app.ai.base import (
    SYSTEM_PROMPT,
    AiProviderFailure,
    AiProviderResponse,
    decision_json_schema,
    extract_provider_usage,
    parse_decision,
)
from app.providers.common import create_system_ssl_context


class AnthropicDecisionProvider:
    name = "anthropic"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str,
        timeout_seconds: float,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.model = model
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout_seconds,
            verify=create_system_ssl_context(),
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
        )

    async def decide(self, snapshot_input: str) -> AiProviderResponse:
        response = await self._client.post(
            "/messages",
            json={
                "model": self.model,
                "max_tokens": 2_048,
                "system": SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": snapshot_input}],
                "output_config": {
                    "format": {
                        "type": "json_schema",
                        "schema": decision_json_schema(),
                    }
                },
            },
        )
        response.raise_for_status()
        raw = _object(response.json(), "Anthropic response")
        stop_reason = raw.get("stop_reason")
        if stop_reason in {"refusal", "max_tokens"}:
            raise AiProviderFailure(
                f"Anthropic stopped with {stop_reason}",
                parse_status="REFUSED" if stop_reason == "refusal" else "INCOMPLETE",
                raw_response=raw,
            )
        text = _text(raw)
        return AiProviderResponse(
            raw_response=raw,
            decision=parse_decision(text, raw),
            model_version=str(raw.get("model") or self.model),
            usage=extract_provider_usage(raw),
        )

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()


def _text(payload: dict[str, Any]) -> str:
    for content in payload.get("content", []):
        if isinstance(content, dict) and content.get("type") == "text":
            text = content.get("text")
            if isinstance(text, str):
                return text
    raise AiProviderFailure(
        "Anthropic response has no text content",
        parse_status="PARSE_FAILED",
        raw_response=payload,
    )


def _object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AiProviderFailure(f"{label} is not an object", parse_status="PARSE_FAILED")
    return value
