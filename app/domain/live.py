from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class DltvFastPatch(BaseModel):
    model_config = ConfigDict(frozen=True)

    valve_match_id: int
    updates: dict[str, Any]
    source_game_time: int | None = Field(default=None, ge=0)
    message_received_at: datetime
    payload_hash: str
    connection_id: str | None = None
    reconnect_generation: int = Field(default=0, ge=0)


class DltvFastState(BaseModel):
    model_config = ConfigDict(frozen=True)

    valve_match_id: int
    game_time_seconds: int | None = Field(default=None, ge=0)
    radiant_kills: int | None = Field(default=None, ge=0)
    dire_kills: int | None = Field(default=None, ge=0)
    radiant_nw_lead: int | None = None
    first_blood: str | None = None
    source_game_time: int | None = Field(default=None, ge=0)
    last_message_received_at: datetime
    last_state_change_received_at: datetime
    state_hash: str
    last_payload_hash: str
    connection_id: str | None = None
    reconnect_generation: int = Field(default=0, ge=0)


class DltvReduction(BaseModel):
    model_config = ConfigDict(frozen=True)

    state: DltvFastState | None
    changed: bool
    duplicate: bool
    warnings: tuple[str, ...] = ()


class LiveSynchronizationEstimate(BaseModel):
    model_config = ConfigDict(frozen=True)

    canonical_map_id: str
    estimated_lag_seconds: float | None
    p50_seconds: float | None
    p90_seconds: float | None
    jitter_seconds: float | None
    sample_size: int = Field(ge=0)
    accepted_pair_ratio: float = Field(ge=0, le=1)
    ambiguous_ratio: float = Field(ge=0, le=1)
    outlier_ratio: float = Field(ge=0, le=1)
    confidence: Literal["LOW", "MEDIUM", "HIGH"]
    status: Literal["SAFE", "CAUTION", "UNSAFE", "CALIBRATING", "UNKNOWN"]
    calculated_at: datetime


class CalibrationPair(BaseModel):
    model_config = ConfigDict(frozen=True)

    raybet_signal_id: str
    dltv_signal_id: str | None
    raybet_received_at: datetime
    dltv_received_at: datetime | None
    lag_seconds: float | None
    raybet_signal_type: str
    dltv_signal_type: str | None
    uniqueness_margin_seconds: float | None
    accepted: bool
    reject_reason: str | None = None
