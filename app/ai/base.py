from dataclasses import dataclass
from typing import Any, Protocol

from app.domain.decision import AiDecision

PROMPT_VERSION = "decision-analyst-v2"
DECISION_POLICY_VERSION = "shadow-decision-v1"

SYSTEM_PROMPT = """You are an independent Dota 2 decision analyst.
Use only the supplied immutable DecisionSnapshot. Do not browse, call tools, or infer missing facts.
UNKNOWN/null values must remain unknown. Deterministic quality blockers override model judgment.
NO_BUY and INSUFFICIENT_DATA are normal outcomes.
Include counter-arguments and data-quality concerns.
When giving reasons, cite the relevant DecisionSnapshot paths.
Assess team A versus team B exactly as identified in the snapshot.
Do not assume team A is Radiant or team B is Dire.

The snapshot is the deterministic ai-view: side-relative values are already mapped
to Team A / Team B by upstream code when side identity is RESOLVED; trust the mapping.
Glossary:
- team_a_vig_adjustment_pp: how much removing the bookmaker margin shifted Team A's
  implied probability. It is a mechanical vig adjustment, NOT a mispricing signal;
  never treat it as evidence that the market undervalues a team.
- odds_drift: how Team A's implied probability moved since the first observation and
  over the last 5 minutes (SHORTENED = the market increasingly favors A).
  The market is real-time; large drift may already price in events the live block cannot show.
- team_a_nw_lead / team_a_nw_delta: Team A net-worth lead / recent change (positive favors A).
- trend_windows (1m/3m/5m/10m): recent live changes; treat momentum as observation, not causality.
- buildings_lost: towers/barracks already destroyed per side; barracks losses imply megacreep risk.
- economy_trajectory: networth_at_10m (laning outcome), max_team_a_deficit/lead (comeback context).
- draft_live_agreement: CONSISTENT/DIVERGENT between draft edge direction and current lead;
  DIVERGENT deserves extra scrutiny.
- position_source / position_confidence: provenance and reliability of draft roles.
- player_stats: per-player level, KDA, net worth, items (age-tagged by observed_at).
- bans: hero bans of the draft.
- live_data_lag_minutes: how far the DLTV live/player data lags the real-time market
  (broadcast delay, often ~15 minutes).
- delayed_live_excluded: when the broadcast lag exceeds the policy threshold, the
  delayed live block (state, trend, buildings, economy, player stats) is withheld
  from this view by design; decide on the remaining freeze-time consistent
  information (real-time market, draft, history) and do not invent live state.
- knowledge_cutoff / observed_at / statistics_cutoff: data timestamps;
  treat data older than the decision time as potentially stale.
- live_sync: alignment quality between odds and live feeds;
  UNKNOWN/CALIBRATING means the live picture may be delayed."""


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
    normalized = {
        name: _strict_schema_type(prop)
        for name, prop in properties.items()
    }
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
        return AiDecision.model_validate_json(text)
    except Exception as exc:
        raise AiProviderFailure(
            f"invalid AI decision JSON: {type(exc).__name__}: {exc}",
            parse_status="PARSE_FAILED",
            raw_response=raw_response,
        ) from exc
