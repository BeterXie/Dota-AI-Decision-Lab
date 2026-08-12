from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class OddsMeta(BaseModel):
    model_config = ConfigDict(frozen=True)

    odds_id: int
    match_id: int
    team_id: int | None
    team_name: str | None
    group_short_name: str | None
    match_stage: str | None
    raw_status: int | None


class OddsDelta(BaseModel):
    model_config = ConfigDict(frozen=True)

    odds_id: int
    match_id: int
    price: Decimal = Field(gt=1)
    raw_status: int | None
    provider_updated_at: datetime | None


class OddsObservation(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider_match_id: int
    odds_id: int
    canonical_series_id: str | None = None
    canonical_map_id: str | None = None
    market_type: str | None = None
    match_stage: str | None = None
    selection_team_id: str | None = None
    price: Decimal = Field(gt=1)
    implied_probability: float
    fair_probability: float | None = None
    overround: float | None = None
    raw_status: int | None = None
    normalized_status: str | None = None
    provider_updated_at: datetime | None = None
    received_at: datetime
    stored_at: datetime


class MarketPairQuality(BaseModel):
    model_config = ConfigDict(frozen=True)

    eligible: bool
    blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    metadata_version: str | None = None
    paired_at: datetime
    pair_skew_seconds: float | None = Field(default=None, ge=0)
