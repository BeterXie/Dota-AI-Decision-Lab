from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class JobStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    RETRY_WAIT = "RETRY_WAIT"
    SUCCEEDED = "SUCCEEDED"
    FAILED_TERMINAL = "FAILED_TERMINAL"
    CANCELLED = "CANCELLED"


class JobType(StrEnum):
    REFRESH_ODDS_REGISTRY = "REFRESH_ODDS_REGISTRY"
    BOOTSTRAP_DLTV_MATCH = "BOOTSTRAP_DLTV_MATCH"
    SYNC_HISTORICAL = "SYNC_HISTORICAL"
    BUILD_DRAFT_CURVE = "BUILD_DRAFT_CURVE"
    BUILD_SNAPSHOT = "BUILD_SNAPSHOT"
    RUN_AI_PROVIDER = "RUN_AI_PROVIDER"
    SEND_DECISION_EMAIL = "SEND_DECISION_EMAIL"
    CAPTURE_FUTURE_ODDS = "CAPTURE_FUTURE_ODDS"
    RESOLVE_POSTMATCH = "RESOLVE_POSTMATCH"
    SETTLE_MAP = "SETTLE_MAP"
    EVALUATE_DECISION = "EVALUATE_DECISION"


class DurableJob(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    job_type: JobType
    dedupe_key: str
    payload: dict[str, Any]
    status: JobStatus
    priority: int
    not_before: datetime
    attempt_count: int = Field(ge=0)
    max_attempts: int = Field(gt=0)
    locked_by: str | None
    locked_at: datetime | None
