from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class DraftSlot(BaseModel):
    model_config = ConfigDict(frozen=True)

    side: Literal["radiant", "dire"]
    position: Literal[1, 2, 3, 4, 5]
    account_id: int | None
    canonical_player_id: str | None = None
    hero_id: int = Field(gt=0)
    source: Literal["DLTV_SLOT", "DLTV_PLAYER_HERO", "INFERRED", "MANUAL"]
    confidence: float = Field(ge=0, le=1)


class DraftValidation(BaseModel):
    model_config = ConfigDict(frozen=True)

    complete: bool
    slots: tuple[DraftSlot, ...]
    blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


class DraftMinutePoint(BaseModel):
    model_config = ConfigDict(frozen=True)

    minute: int = Field(ge=20, le=60)
    pure_radiant_edge: float | None = None
    adjusted_radiant_edge: float | None = None
    support: int | None = Field(default=None, ge=0)
    confidence: float | None = Field(default=None, ge=0, le=1)


class DraftDerivedFeatures(BaseModel):
    model_config = ConfigDict(frozen=True)

    current_minute: int | None = None
    current_edge: float | None = None
    next_5m_edge: float | None = None
    next_10m_edge: float | None = None
    peak_minute: int | None = None
    peak_edge: float | None = None
    cross_over_minute: int | None = None
    early_average: float | None = None
    mid_average: float | None = None
    late_average: float | None = None
    ultra_late_average: float | None = None
    curve_slope_5m: float | None = None
    curve_slope_10m: float | None = None


class DraftCurve(BaseModel):
    model_config = ConfigDict(frozen=True)

    points: tuple[DraftMinutePoint, ...]
    features: DraftDerivedFeatures
    statistics_cutoff: datetime
    model_version: str
    data_version: str
