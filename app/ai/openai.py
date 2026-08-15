from typing import Any

import httpx

from app.ai.base import (
    SYSTEM_PROMPT,
    AiProviderFailure,
    AiProviderResponse,
    decision_json_schema,
    parse_decision,
)
from app.providers.common import create_system_ssl_context


class OpenAiDecisionProvider:
    name = "openai"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str,
        reasoning_effort: str,
        timeout_seconds: float,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.model = model
        self.reasoning_effort = reasoning_effort
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout_seconds,
            verify=create_system_ssl_context(),
            headers={"Authorization": f"Bearer {api_key}"},
        )

    async def decide(self, snapshot_input: str) -> AiProviderResponse:
        response = await self._client.post(
            "/responses",
            json={
                "model": self.model,
                "reasoning": {"effort": self.reasoning_effort},
                "instructions": SYSTEM_PROMPT,
                "input": snapshot_input,
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": "dota_ai_decision",
                        "schema": decision_json_schema(),
                        "strict": True,
                    }
                },
            },
        )
        response.raise_for_status()
        raw = _object(response.json(), f"{self.name} response")
        if raw.get("status") != "completed":
            raise AiProviderFailure(
                f"{self.name} response status is {raw.get('status')}",
                parse_status="FAILED",
                raw_response=raw,
            )
        text = response_output_text(raw, provider_name=self.name)
        return AiProviderResponse(
            raw_response=raw,
            decision=parse_decision(text, raw),
            model_version=str(raw.get("model") or self.model),
        )

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()


class LocalOpenAiDecisionProvider(OpenAiDecisionProvider):
    name = "local_openai"


def response_output_text(payload: dict[str, Any], *, provider_name: str) -> str:
    for item in payload.get("output", []):
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if isinstance(content, dict) and content.get("type") == "refusal":
                raise AiProviderFailure(
                    f"{provider_name} refused the decision request",
                    parse_status="REFUSED",
                    raw_response=payload,
                )
            if isinstance(content, dict) and content.get("type") == "output_text":
                text = content.get("text")
                if isinstance(text, str):
                    return text
    raise AiProviderFailure(
        f"{provider_name} response has no output text",
        parse_status="PARSE_FAILED",
        raw_response=payload,
    )


def _object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AiProviderFailure(f"{label} is not an object", parse_status="PARSE_FAILED")
    return value
