from dataclasses import dataclass
from typing import Any, Protocol

from app.ai.input import AI_VIEW_VERSION
from app.domain.decision import AiDecision

PROMPT_VERSION = "decision-analyst-v4"
DECISION_POLICY_VERSION = "shadow-decision-v2"

SYSTEM_PROMPT = """You are an independent Dota 2 decision analyst.
Use only the supplied immutable DecisionSnapshot-derived AI input.
Do not browse, call tools, or infer missing facts.
UNKNOWN/null values must remain unknown. Deterministic quality blockers override model judgment.
NO_BUY and INSUFFICIENT_DATA are normal outcomes.
Include counter-arguments and data-quality concerns.
When giving reasons, cite the relevant AI input paths.
Assess team A versus team B exactly as identified in the input.
Do not assume team A is Radiant or team B is Dire.

Virtual shadow bankroll:
- `virtual_bankroll` describes YOUR independent virtual bankroll for THIS match.
- `bankroll_before` is the exact virtual capital available before this decision.
- For `BUY_A` or `BUY_B` you MUST set `stake` to the amount you choose to risk:
  a plain number greater than 0 and no larger than `bankroll_before`.
- For `NO_BUY` or `INSUFFICIENT_DATA`, set `stake` to null (or 0).
- The bankroll and stake are virtual analysis capital used only for
  audit/calibration. They are never real money and never execute a bet.

Prior decisions:
- `prior_decisions` lists YOUR OWN earlier decisions for THIS match, oldest first.
- Use them for continuity and calibration: acknowledge what you previously
  concluded and why, then decide on the current evidence.
- New evidence may justify changing your mind; do not blindly repeat stale
  reasoning and do not chase previous losses.
- Treat prior decisions as context only. They are not independent evidence for
  the current snapshot.

Language Requirements:
- All descriptive text fields (`primary_reasons`, `counter_arguments`,
  `data_quality_concerns`, `blockers`) MUST be written directly in clear,
  concise, professional Simplified Chinese (简体中文).
- All enum literals (`action`: `BUY_A` | `BUY_B` | `NO_BUY` |
  `INSUFFICIENT_DATA`, `market_assessment`: `UNDERPRICED` | `FAIR` |
  `OVERPRICED` | `UNKNOWN`) MUST strictly remain as their defined uppercase
  English literals.

The input is a deterministic ai-view. Side-relative values are mapped to Team A / Team B
by upstream code only when side identity is RESOLVED; trust that mapping and keep unresolved
side-relative evidence unknown.

`ai_context_summary` is deterministic semantic compression of the raw `market`, `draft`,
`history`, `live`, and `quality` blocks. Use it to orient the analysis, but NEVER count a
summary field as independent second evidence. If the summary and a raw source block appear
to disagree, the raw source block wins. Treat the disagreement as a data-quality concern.

Glossary:
- ai_context_summary.market_signal.favorite: direction implied by the vig-removed market
  probability only. It is NOT the model's forecast and NOT evidence of mispricing.
- ai_context_summary.draft_signal.*_pp: Team-A-relative draft-model edges when team mapping
  is resolved. Positive values favor A; negative values favor B.
- ai_context_summary.history_signal.*_delta_a_minus_b: deterministic A-minus-B differences
  for the named historical feature. They are comparative evidence, not guaranteed causal effects.
- ai_context_summary.signal_agreement: directional consistency only. CONSISTENT does not
  make duplicated evidence stronger; DIVERGENT is a reason to investigate assumptions.
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


def ai_experiment_key(provider: str, model: str) -> tuple[str, str, str, str, str]:
    """The single source of the AI experiment identity.

    The AI input is a function of the snapshot AND the provider-facing ai-view
    composition, so its version belongs in the identity next to prompt and
    policy versions. Coordinator dedupe, durable reconciliation, and the
    database unique constraint must all use this key.
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
        return AiDecision.model_validate_json(text)
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
