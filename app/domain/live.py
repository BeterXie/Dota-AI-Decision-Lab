from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class DltvFastState(BaseModel):
    model_config = ConfigDict(frozen=True)

    valve_match_id: int
    game_time_seconds: int | None = Field(default=None, ge=0)
    radiant_kills: int | None = Field(default=None, ge=0)
    dire_kills: int | None = Field(default=None, ge=0)
    radiant_nw_lead: int | None = None
    first_blood: str | None = None
    source_game_time: int | None = Field(default=None, ge=0)
    received_at: datetime
    payload_hash: str


class LiveSynchronizationEstimate(BaseModel):
    model_config = ConfigDict(frozen=True)

    canonical_map_id: str
    estimated_lag_seconds: float | None
    p50_seconds: float | None
    p90_seconds: float | None
    jitter_seconds: float | None
    sample_size: int = Field(ge=0)
    confidence: Literal["LOW", "MEDIUM", "HIGH"]
    status: Literal["SAFE", "CAUTION", "UNSAFE", "UNKNOWN"]
    calculated_at: datetime
