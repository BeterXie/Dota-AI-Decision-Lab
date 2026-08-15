from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

LEGACY_EXPLANATION_FIELDS = frozenset({"counter_arguments", "data_quality_concerns"})


class AiDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    action: Literal["BUY_A", "BUY_B", "NO_BUY", "INSUFFICIENT_DATA"]
    fair_probability_a: float | None = Field(default=None, ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    market_assessment: Literal["UNDERPRICED", "FAIR", "OVERPRICED", "UNKNOWN"]
    minimum_acceptable_odds_a: float | None = Field(default=None, gt=1)
    # Virtual shadow capital chosen by the model for BUY actions. It is
    # constrained upstream against the provider/match virtual bankroll and is
    # never real money or an automatic execution instruction.
    stake: float | None = Field(default=None, ge=0)
    primary_reasons: list[str]
    blockers: list[str]

    @model_validator(mode="before")
    @classmethod
    def _discard_legacy_explanation_fields(cls, value: Any) -> Any:
        """Read historical normalized decisions without re-emitting retired fields.

        Provider responses are checked separately before validation, so this compatibility
        path is only for stored/fixture payloads created by older prompt versions.
        """
        if not isinstance(value, dict) or LEGACY_EXPLANATION_FIELDS.isdisjoint(value):
            return value
        cleaned = dict(value)
        for field in LEGACY_EXPLANATION_FIELDS:
            cleaned.pop(field, None)
        return cleaned


def target_probability(action: str | None, fair_probability_a: float | None) -> float | None:
    """Return the win probability for the side targeted by ``action``.

    The model emits ``fair_probability_a`` (Team A's win probability) for every
    action.  When the conclusion is ``BUY_B``, the supported target is Team B,
    so presentation layers must invert the probability.  Keeping that inversion
    here stops WeChat, email and the web dashboard from drifting apart.
    """
    if action == "BUY_B" and fair_probability_a is not None:
        return 1.0 - fair_probability_a
    return fair_probability_a
