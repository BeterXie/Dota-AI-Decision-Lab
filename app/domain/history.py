from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class HistoricalMap(BaseModel):
    model_config = ConfigDict(frozen=True)

    canonical_map_id: str | None = None
    provider_match_id: str
    event_id: str | None = None
    event_name: str | None = None
    patch_id: str | None = None
    started_at: datetime
    started_at_estimated: bool = False
    ended_at: datetime | None = None
    radiant_team_id: str | None = None
    dire_team_id: str | None = None
    winner_team_id: str | None = None
    duration_seconds: int | None = Field(default=None, ge=0)
    provider: str
    first_usable_at: datetime
    fetched_at: datetime


class PlayerHistoricalMap(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider_match_id: str
    account_id: int
    team_id: str | None = None
    opponent_team_id: str | None = None
    hero_id: int
    position: int | None = Field(default=None, ge=1, le=5)
    patch_id: str | None = None
    started_at: datetime
    first_usable_at: datetime
    won: bool
    kills: int | None = None
    deaths: int | None = None
    assists: int | None = None
    gpm: float | None = None
    xpm: float | None = None
    last_hits: int | None = None
    hero_damage: float | None = None
    tower_damage: float | None = None
    networth: float | None = None
    impact: float | None = None


class HistoricalMatchBundle(BaseModel):
    model_config = ConfigDict(frozen=True)

    match: HistoricalMap
    players: tuple[PlayerHistoricalMap, ...]
    advanced_available: bool
    warnings: tuple[str, ...] = ()


class TeamStrengthSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    canonical_team_id: str
    base_rating: float | None
    base_rating_percentile: float | None = None
    recent_form: float | None
    last_5_wins: int = 0
    last_5_maps: int = 0
    last_10_wins: int = 0
    last_10_maps: int = 0
    last_20_wins: int = 0
    last_20_maps: int = 0
    current_roster_strength: float | None = None
    roster_stability: float | None = None
    exact_roster_map_count: int = 0
    confidence: float = Field(ge=0, le=1)
    knowledge_cutoff: datetime
    calculated_at: datetime
    model_version: str


class PlayerFeatureSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    canonical_player_id: str
    account_id: int
    position: int = Field(ge=1, le=5)
    base_strength: float | None
    recent_form: float | None
    recent_5: float | None = None
    recent_10: float | None = None
    recent_20: float | None = None
    maps_5: int = 0
    maps_10: int = 0
    maps_20: int = 0
    confidence: float = Field(ge=0, le=1)
    knowledge_cutoff: datetime
    calculated_at: datetime
    model_version: str


class PlayerHeroSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    canonical_player_id: str
    account_id: int
    hero_id: int
    position: int = Field(ge=1, le=5)
    historical_maps: int = 0
    historical_win_rate: float | None = None
    historical_performance: float | None = None
    recent_180d_maps: int = 0
    recent_180d_win_rate: float | None = None
    recent_180d_performance: float | None = None
    current_patch_maps: int = 0
    current_patch_win_rate: float | None = None
    current_patch_performance: float | None = None
    position_fit: float | None = None
    raw_strength: float | None = None
    adjusted_strength: float | None = None
    confidence: float = Field(ge=0, le=1)
    knowledge_cutoff: datetime
    calculated_at: datetime
    model_version: str


class HistoricalQuality(BaseModel):
    model_config = ConfigDict(frozen=True)

    team_strength_ready: bool
    roster_confirmed: bool
    player_form_ready_count: int
    player_hero_ready_count: int
    oldest_feature_age_seconds: float | None
    blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
