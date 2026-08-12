from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AiDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    action: Literal["BUY_A", "BUY_B", "NO_BUY", "INSUFFICIENT_DATA"]
    fair_probability_a: float | None = Field(default=None, ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    market_assessment: Literal["UNDERPRICED", "FAIR", "OVERPRICED", "UNKNOWN"]
    minimum_acceptable_odds_a: float | None = Field(default=None, gt=1)
    primary_reasons: list[str]
    counter_arguments: list[str]
    data_quality_concerns: list[str]
    blockers: list[str]
