from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class DecisionMode(StrEnum):
    PREMATCH = "PREMATCH"
    POST_DRAFT = "POST_DRAFT"
    LIVE_BASIC = "LIVE_BASIC"
    LIVE_FULL = "LIVE_FULL"


class GateResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    eligible: bool
    mode: DecisionMode
    blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


class DecisionSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    snapshot_id: UUID
    decision_at: datetime
    created_at: datetime
    mode: DecisionMode
    identity: dict[str, Any]
    market: dict[str, Any]
    draft: dict[str, Any] | None
    history: dict[str, Any]
    live: dict[str, Any] | None
    quality: dict[str, Any]
    snapshot_hash: str
