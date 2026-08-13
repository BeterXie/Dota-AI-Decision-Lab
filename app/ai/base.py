from dataclasses import dataclass
from typing import Any, Protocol

from app.domain.decision import AiDecision

PROMPT_VERSION = "decision-analyst-v2"
DECISION_POLICY_VERSION = "shadow-decision-v1"

SYSTEM_PROMPT = """You are an independent Dota 2 decision analyst.
Use only the supplied immutable DecisionSnapshot. Do not browse, call tools, or infer missing facts.
UNKNOWN/null values must remain unknown. Deterministic quality blockers override model judgment.
NO_BUY and INSUFFICIENT_DATA are normal outcomes.
Separate current STATE, recent TREND, and historical/Draft CONTEXT when reasoning; do not treat correlation or momentum as proven causality.
Respect sample size, confidence, position_source, position_confidence, knowledge_cutoff, freshness, and temporal-alignment quality. Small Player×Hero samples must not be treated as certain skill estimates.
R.O.S.H. decomposition is deterministic upstream evidence; do not recalculate or override its component values.
Include counter-arguments and data-quality concerns.
When giving reasons, cite the relevant DecisionSnapshot paths.
Assess team A versus team B exactly as identified in the snapshot; do not assume team A is Radiant or team B is Dire."""


@dataclass(frozen=True)
class AiProviderResponse:
    raw_response: dict[str, Any]
    decision: AiDecision
    model_version: str


class AiProviderFailure(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        parse_status: str,
        raw_response: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.parse_status = parse_status
        self.raw_response = raw_response


class AiProvider(Protocol):
    name: str
    model: str

    async def decide(self, snapshot_input: str) -> AiProviderResponse: ...

    async def close(self) -> None: ...


def decision_json_schema() -> dict[str, Any]:
    nullable_number = {"type": ["number", "null"]}
    string_array = {"type": "array", "items": {"type": "string"}}
    return {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["BUY_A", "BUY_B", "NO_BUY", "INSUFFICIENT_DATA"],
            },
            "fair_probability_a": nullable_number,
            "confidence": {"type": "number"},
            "market_assessment": {
                "type": "string",
                "enum": ["UNDERPRICED", "FAIR", "OVERPRICED", "UNKNOWN"],
            },
            "minimum_acceptable_odds_a": nullable_number,
            "primary_reasons": string_array,
            "counter_arguments": string_array,
            "data_quality_concerns": string_array,
            "blockers": string_array,
        },
        "required": [
            "action",
            "fair_probability_a",
            "confidence",
            "market_assessment",
            "minimum_acceptable_odds_a",
            "primary_reasons",
            "counter_arguments",
            "data_quality_concerns",
            "blockers",
        ],
        "additionalProperties": False,
    }


def parse_decision(text: str, raw_response: dict[str, Any]) -> AiDecision:
    try:
        return AiDecision.model_validate_json(text)
    except Exception as exc:
        raise AiProviderFailure(
            f"invalid AI decision JSON: {type(exc).__name__}: {exc}",
            parse_status="PARSE_FAILED",
            raw_response=raw_response,
        ) from exc
