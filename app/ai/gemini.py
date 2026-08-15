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


class GeminiDecisionProvider:
    name = "gemini"

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
            headers={"x-goog-api-key": api_key},
        )

    async def decide(self, snapshot_input: str) -> AiProviderResponse:
        response = await self._client.post(
            "/interactions",
            json={
                "model": self.model,
                "system_instruction": SYSTEM_PROMPT,
                "input": snapshot_input,
                "response_format": [
                    {
                        "type": "text",
                        "mime_type": "application/json",
                        "schema": decision_json_schema(),
                    }
                ],
            },
        )
        response.raise_for_status()
        raw = _object(response.json(), "Gemini response")
        if raw.get("status") not in {None, "completed"}:
            raise AiProviderFailure(
                f"Gemini interaction status is {raw.get('status')}",
                parse_status="FAILED",
                raw_response=raw,
            )
        text = _output_text(raw)
        return AiProviderResponse(
            raw_response=raw,
            decision=parse_decision(text, raw),
            model_version=str(raw.get("model") or self.model),
            usage=extract_provider_usage(raw),
        )

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()


def _output_text(payload: dict[str, Any]) -> str:
    for step in reversed(payload.get("steps", [])):
        if not isinstance(step, dict) or step.get("type") != "model_output":
            continue
        for content in step.get("content", []):
            if isinstance(content, dict) and content.get("type") == "text":
                text = content.get("text")
                if isinstance(text, str):
                    return text
    raise AiProviderFailure(
        "Gemini response has no model output text",
        parse_status="PARSE_FAILED",
        raw_response=payload,
    )


def _object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AiProviderFailure(f"{label} is not an object", parse_status="PARSE_FAILED")
    return value
