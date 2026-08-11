from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ProviderMatch(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider_match_id: int
    game_id: int
    tournament_id: int | None
    tournament_name: str | None
    team_a_id: int
    team_a_name: str
    team_b_id: int
    team_b_name: str
    round: str | None
    provider_status: int | None
    scheduled_at: datetime | None
    observed_at: datetime


class MatchCandidate(BaseModel):
    model_config = ConfigDict(frozen=True)

    canonical_map_id: str
    valve_match_id: int | None = None
    event_id: str | None = None
    team_ids: frozenset[str]
    scheduled_at: datetime | None = None


class MatchResolution(BaseModel):
    model_config = ConfigDict(frozen=True)

    canonical_map_id: str | None
    method: str | None
    confidence: float
    blocker: str | None = None
