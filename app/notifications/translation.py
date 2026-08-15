import json
from dataclasses import dataclass
from typing import Any

import httpx

from app.ai.openai import response_output_text
from app.models import AiDecisionRecord
from app.providers.common import create_system_ssl_context


@dataclass(frozen=True, slots=True)
class EmailTranslationResult:
    translations: dict[str, dict[str, Any]]
    raw_response: dict[str, Any]
    model_version: str


class DeepSeekEmailTranslator:
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
        self._reasoning_effort = reasoning_effort
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout_seconds,
            verify=create_system_ssl_context(),
            headers={"Authorization": f"Bearer {api_key}"},
        )

    async def translate(self, decisions: list[AiDecisionRecord]) -> EmailTranslationResult:
        source = [
            {
                "decision_id": str(record.id),
                "provider": record.provider,
                "model": record.model,
                "primary_reasons": _strings(record.normalized_response, "primary_reasons"),
                "blockers": _strings(record.normalized_response, "blockers"),
                "error": record.error,
            }
            for record in decisions
        ]
        response = await self._client.post(
            "/responses",
            json={
                "model": self.model,
                "reasoning": {"effort": self._reasoning_effort},
                "instructions": (
                    "你是Dota 2比赛决策邮件翻译器。把输入中的英文观点准确翻译成普通中文，"
                    "让普通Dota 2玩家能看懂。保留队名、英雄名、数字和专有名词；不要增加、"
                    "删除或推断任何事实；blocker代码翻译为简短中文含义。只输出指定JSON。"
                ),
                "input": json.dumps(source, ensure_ascii=False),
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": "decision_email_translation",
                        "schema": _translation_schema(),
                        "strict": True,
                    }
                },
            },
        )
        response.raise_for_status()
        raw = response.json()
        if not isinstance(raw, dict):
            raise ValueError("DeepSeek translation response is not an object")
        if raw.get("status") != "completed":
            raise ValueError(f"DeepSeek translation status is {raw.get('status')}")
        parsed = json.loads(response_output_text(raw, provider_name="deepseek translation"))
        rows = parsed.get("translations") if isinstance(parsed, dict) else None
        if not isinstance(rows, list):
            raise ValueError("DeepSeek translation output is missing translations")
        translations = {
            row["decision_id"]: row
            for row in rows
            if isinstance(row, dict) and isinstance(row.get("decision_id"), str)
        }
        expected_ids = {str(record.id) for record in decisions}
        if set(translations) != expected_ids:
            raise ValueError("DeepSeek translation output does not match decision ids")
        return EmailTranslationResult(
            translations=translations,
            raw_response=raw,
            model_version=str(raw.get("model") or self.model),
        )

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()


def _strings(value: dict | None, key: str) -> list[str]:
    items = value.get(key) if isinstance(value, dict) else None
    return [str(item) for item in items] if isinstance(items, list) else []


def _translation_schema() -> dict[str, Any]:
    properties: dict[str, Any] = {
        "decision_id": {"type": "string"},
        "primary_reasons": {"type": "array", "items": {"type": "string"}},
        "blockers": {"type": "array", "items": {"type": "string"}},
        "error": {"type": ["string", "null"]},
    }
    return {
        "type": "object",
        "properties": {
            "translations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": properties,
                    "required": list(properties),
                    "additionalProperties": False,
                },
            }
        },
        "required": ["translations"],
        "additionalProperties": False,
    }
