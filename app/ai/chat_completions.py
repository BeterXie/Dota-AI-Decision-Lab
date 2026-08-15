from typing import Any

import httpx

from app.ai.base import (
    SYSTEM_PROMPT,
    AiProviderFailure,
    AiProviderResponse,
    parse_decision,
)
from app.providers.common import create_system_ssl_context


class ChatCompletionsDecisionProvider:
    name: str

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
            headers={"Authorization": f"Bearer {api_key}"},
        )

    async def decide(self, snapshot_input: str) -> AiProviderResponse:
        response = await self._client.post(
            "/chat/completions",
            json={
                "model": self.model,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            f"{SYSTEM_PROMPT}\nReturn JSON only. "
                            "Use exactly these fields and value types: "
                            '{"action":"BUY_A|BUY_B|NO_BUY|INSUFFICIENT_DATA",'
                            '"fair_probability_a":null,"confidence":0.0,'
                            '"market_assessment":"UNDERPRICED|FAIR|OVERPRICED|UNKNOWN",'
                            '"minimum_acceptable_odds_a":null,"stake":null,'
                            '"primary_reasons":[],'
                            '"counter_arguments":[],"data_quality_concerns":[],"blockers":[]}. '
                            "Use at most three concise strings in each array. No markdown."
                        ),
                    },
                    {"role": "user", "content": snapshot_input},
                ],
                "response_format": {"type": "json_object"},
                "thinking": {"type": "disabled"},
                "max_tokens": 4_096,
                "stream": False,
            },
        )
        response.raise_for_status()
        try:
            raw = _object(response.json(), f"{self.name} response")
        except ValueError as exc:
            raise AiProviderFailure(
                f"{self.name} response is not JSON",
                parse_status="PARSE_FAILED",
            ) from exc
        choices = raw.get("choices")
        if not isinstance(choices, list) or not choices:
            raise AiProviderFailure(
                f"{self.name} response has no choices",
                parse_status="PARSE_FAILED",
                raw_response=raw,
            )
        choice = _object(choices[0], f"{self.name} choice")
        if choice.get("finish_reason") != "stop":
            raise AiProviderFailure(
                f"{self.name} finish reason is {choice.get('finish_reason')}",
                parse_status="FAILED",
                raw_response=raw,
            )
        message = _object(choice.get("message"), f"{self.name} message")
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise AiProviderFailure(
                f"{self.name} response has no message content",
                parse_status="PARSE_FAILED",
                raw_response=raw,
            )
        return AiProviderResponse(
            raw_response=raw,
            decision=parse_decision(content, raw),
            model_version=str(raw.get("model") or self.model),
        )

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()


class KimiDecisionProvider(ChatCompletionsDecisionProvider):
    name = "kimi"


def _object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AiProviderFailure(f"{label} is not an object", parse_status="PARSE_FAILED")
    return value
