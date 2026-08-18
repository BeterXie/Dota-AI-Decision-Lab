from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class LiquipediaTournamentObservation(BaseModel):
    model_config = ConfigDict(frozen=True)

    page_name: str
    name: str
    phase: Literal["UPCOMING", "ONGOING", "COMPLETED"]
    tier: str | None = None
    date_label: str | None = None
    source_href: str


class LiquipediaSeriesObservation(BaseModel):
    model_config = ConfigDict(frozen=True)

    team_a_name: str
    team_a_page: str | None = None
    team_b_name: str
    team_b_page: str | None = None
    tournament_name: str | None = None
    tournament_page: str | None = None
    stage: str | None = None
    best_of: int | None = None
    scheduled_at: datetime | None = None
    state: Literal["UPCOMING", "COMPLETED", "UNKNOWN"] = "UNKNOWN"
    provider_key: str
