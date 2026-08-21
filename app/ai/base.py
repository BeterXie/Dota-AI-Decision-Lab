import hashlib
import json
from dataclasses import dataclass
from typing import Any, Protocol

from app.ai.input import AI_VIEW_VERSION
from app.domain.decision import LEGACY_EXPLANATION_FIELDS, AiDecision
from app.domain.experiment import AiDecisionLaneKey

PROMPT_VERSION = "decision-analyst-v5.1-output"
DECISION_POLICY_VERSION = "shadow-tournament-portfolio-v3"

SYSTEM_PROMPT = """You are an independent Dota 2 decision analyst.
Use only the supplied immutable DecisionSnapshot-derived AI input. Never browse, call
tools, invent facts, or resolve UNKNOWN/null values yourself. Deterministic quality
blockers override model judgment. NO_BUY and INSUFFICIENT_DATA are normal outcomes.

Assess Team A versus Team B exactly as identified by the input. Never assume Team A is
Radiant or Team B is Dire. Use side-relative evidence only when upstream side identity
is RESOLVED.

Decision/output rules:
- Preserve the schema-defined meanings of action, fair_probability_a, confidence,
  market_assessment, minimum_acceptable_odds_a, and stake.
- virtual_bankroll is one shared canonical-event shadow portfolio for this
  provider/model experiment. bankroll_before is available cash after prior settled P&L
  and currently locked positions; locked_balance cannot be staked again.
- BUY_A/BUY_B require 0 < stake <= virtual_bankroll.bankroll_before.
  If virtual_bankroll.scope is UNRESOLVED_CANONICAL_EVENT, or bankroll_before is 0,
  do not BUY: the tournament account cannot be identified safely yet.
  NO_BUY/INSUFFICIENT_DATA use stake null/0. Stake is virtual audit capital only.
- Before finalizing, internally challenge the leading conclusion with the strongest
  contrary evidence and data-quality limitations. Reflect material uncertainty in
  fair_probability_a/confidence and, when decision-relevant, primary_reasons.
- Do not output separate counter-argument or data-quality-concern lists. Use blockers
  only for conditions that prevent a reliable decision.
- Reasons must cite relevant AI-input paths.
- All descriptive strings must be clear professional Simplified Chinese. Enum literals
  remain the schema-defined uppercase English values.

Evidence rules:
- ai_context_summary is deterministic compression of market/draft/history/live/quality,
  not independent evidence. Use it only to orient analysis and never double-count it.
  If summary and raw blocks disagree, raw evidence wins and the mismatch is a quality concern.
- market_signal.favorite is only the direction of vig-removed market probability, not a
  model forecast or mispricing signal. team_a_vig_adjustment_pp is mechanical vig
  adjustment, never evidence of undervaluation.
- Positive Team-A-relative draft/history/live deltas or edges favor A; negative values
  favor B. Historical comparisons are comparative evidence, not guaranteed causal effects.
- signal_agreement is directional consistency only. CONSISTENT does not strengthen
  duplicated evidence; DIVERGENT warrants scrutiny.
- odds_drift is Team A implied-probability movement. The market is real-time and may
  already price events absent from delayed live data.
- team_a_nw_lead/team_a_nw_delta and trend_windows describe observed state/momentum,
  not causality. buildings_lost and economy_trajectory are state/context; barracks losses
  imply megacreep risk.
- draft_live_agreement DIVERGENT warrants scrutiny. Respect position_source,
  position_confidence, player_stats observed_at, and bans as evidence provenance/freshness.
- live_data_lag_minutes compares delayed live/player data with the real-time market. If
  delayed_live_excluded=true, do not infer withheld live state, trend, buildings,
  economy, or player stats.
- knowledge_cutoff, observed_at, and statistics_cutoff define freshness. live_sync
  UNKNOWN/CALIBRATING means live alignment may be delayed and should reduce confidence.

Prior decisions:
prior_decisions are your own earlier decisions for this match, oldest first. Use them
only for continuity and calibration, never as independent current evidence. New evidence
may change the conclusion; do not blindly repeat stale reasoning or chase previous losses.
"""


@dataclass(frozen=True)
class AiProviderUsage:
    input_tokens: int | None = None
    cached_input_tokens: int | None = None
    reasoning_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


@dataclass(frozen=True)
class AiProviderResponse:
    raw_response: dict[str, Any]
    decision: AiDecision
    model_version: str
    usage: AiProviderUsage | None = None


def ai_prompt_cache_key(provider: str, model: str) -> str:
    identity = f"{provider}|{model}|{PROMPT_VERSION}|{DECISION_POLICY_VERSION}|{AI_VIEW_VERSION}"
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]
    return f"dota-ai-decision:{digest}"


def extract_provider_usage(payload: dict[str, Any] | None) -> AiProviderUsage | None:
    if not isinstance(payload, dict):
        return None
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        usage = payload.get("usageMetadata")
    if not isinstance(usage, dict):
        return None

    input_details = usage.get("input_tokens_details")
    output_details = usage.get("output_tokens_details")
    completion_details = usage.get("completion_tokens_details")
    input_details = input_details if isinstance(input_details, dict) else {}
    output_details = output_details if isinstance(output_details, dict) else {}
    completion_details = completion_details if isinstance(completion_details, dict) else {}

    cache_read = _usage_int(usage.get("cache_read_input_tokens"))
    cache_creation = _usage_int(usage.get("cache_creation_input_tokens"))
    input_tokens = _first_usage_int(
        usage.get("total_input_tokens"),
        usage.get("input_tokens"),
        usage.get("prompt_tokens"),
    )
    # Anthropic reports uncached/cache-write/cache-read input separately.
    if cache_read is not None or cache_creation is not None:
        input_tokens = (
            (_usage_int(usage.get("input_tokens")) or 0) + (cache_read or 0) + (cache_creation or 0)
        )
    cached_input_tokens = _first_usage_int(
        usage.get("total_cached_tokens"),
        input_details.get("cached_tokens"),
        usage.get("prompt_cache_hit_tokens"),
        cache_read,
    )
    output_tokens = _first_usage_int(
        usage.get("total_output_tokens"),
        usage.get("output_tokens"),
        usage.get("completion_tokens"),
    )
    reasoning_tokens = _first_usage_int(
        usage.get("total_thought_tokens"),
        output_details.get("reasoning_tokens"),
        completion_details.get("reasoning_tokens"),
    )
    total_tokens = _usage_int(usage.get("total_tokens"))
    if total_tokens is None and input_tokens is not None and output_tokens is not None:
        total_tokens = input_tokens + output_tokens
    values = (
        input_tokens,
        cached_input_tokens,
        reasoning_tokens,
        output_tokens,
        total_tokens,
    )
    if all(value is None for value in values):
        return None
    return AiProviderUsage(
        input_tokens=input_tokens,
        cached_input_tokens=cached_input_tokens,
        reasoning_tokens=reasoning_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
    )


def _first_usage_int(*values: object) -> int | None:
    for value in values:
        parsed = _usage_int(value)
        if parsed is not None:
            return parsed
    return None


def _usage_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return value
    if isinstance(value, float) and value >= 0 and value.is_integer():
        return int(value)
    return None


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


def ai_decision_lane_key(provider: str, model: str) -> AiDecisionLaneKey:
    """Identity used to schedule one provider/model decision lane.

    Runtime execution configuration is frozen later, during PREPARE. The lane
    key therefore drives durable scheduling, while the final AI experiment adds
    that frozen execution-config version before comparison and portfolio use.
    """
    return (provider, model, PROMPT_VERSION, DECISION_POLICY_VERSION, AI_VIEW_VERSION)


def decision_json_schema() -> dict[str, Any]:
    """Provider-facing structured-output schema derived from AiDecision.

    AiDecision is the single source of truth for field names, enums, and
    constraints. Pydantic emits `anyOf` unions for optional fields, which
    OpenAI's strict structured outputs reject; those are normalized to the
    `type: [..., "null"]` form. Every property is marked required because
    strict providers demand it (the model-level default still applies when
    the JSON is parsed back into AiDecision).
    """
    schema = AiDecision.model_json_schema()
    properties: dict[str, Any] = schema.get("properties", {})
    normalized = {name: _strict_schema_type(prop) for name, prop in properties.items()}
    return {
        "type": "object",
        "properties": normalized,
        "required": list(properties),
        "additionalProperties": False,
    }


def _strict_schema_type(node: dict[str, Any]) -> dict[str, Any]:
    branches = node.get("anyOf")
    if isinstance(branches, list) and len(branches) == 2:
        first, second = branches
        if (
            isinstance(first, dict)
            and isinstance(first.get("type"), str)
            and isinstance(second, dict)
            and second.get("type") == "null"
            and set(second) <= {"type"}
        ):
            merged = {key: value for key, value in first.items() if key != "title"}
            merged["type"] = [first["type"], "null"]
            return merged
    return {key: value for key, value in node.items() if key != "title"}


def parse_decision(text: str, raw_response: dict[str, Any]) -> AiDecision:
    try:
        payload = json.loads(text)
        if not isinstance(payload, dict):
            raise ValueError("AI decision must be a JSON object")
        retired = sorted(LEGACY_EXPLANATION_FIELDS.intersection(payload))
        if retired:
            raise ValueError("AI decision contains retired output fields: " + ", ".join(retired))
        return AiDecision.model_validate(payload)
    except Exception as exc:
        raise AiProviderFailure(
            f"invalid AI decision JSON: {type(exc).__name__}: {exc}",
            parse_status="PARSE_FAILED",
            raw_response=raw_response,
        ) from exc


def validate_ai_decision(
    decision: AiDecision,
    *,
    bankroll_before: float,
    raw_response: dict[str, Any] | None = None,
) -> None:
    """Enforce the virtual-shadow-bankroll policy on a parsed decision.

    The model output itself is never rewritten. A violation is a parse-level
    failure: the raw provider response stays stored while the normalized
    decision is withheld from downstream consumers.
    """
    stake = decision.stake
    if decision.action in {"BUY_A", "BUY_B"}:
        if stake is None or stake <= 0:
            raise AiProviderFailure(
                f"{decision.action} requires a positive virtual stake (stake={stake})",
                parse_status="POLICY_FAILED",
                raw_response=raw_response,
            )
        if stake > bankroll_before + 0.005:
            raise AiProviderFailure(
                f"virtual stake {stake} exceeds available bankroll {bankroll_before}",
                parse_status="POLICY_FAILED",
                raw_response=raw_response,
            )
    elif stake is not None and stake != 0:
        raise AiProviderFailure(
            f"{decision.action} must have stake null/0, got {stake}",
            parse_status="POLICY_FAILED",
            raw_response=raw_response,
        )
