from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DltvSeries(BaseModel):
    model_config = ConfigDict(frozen=True)

    series_id: int
    event_id: int | None
    first_team_id: int
    second_team_id: int
    started_at: datetime | None
    status: int | None
    first_team_score: int | None
    second_team_score: int | None


class DltvSeriesFrame(BaseModel):
    model_config = ConfigDict(frozen=True)

    live_maps: dict[int, int]
    series: tuple[DltvSeries, ...]


class DltvBootstrapIdentity(BaseModel):
    model_config = ConfigDict(frozen=True)

    valve_match_id: int
    series_id: int | None
    event_id: int | None
    first_team_id: int
    first_team_name: str
    second_team_id: int
    second_team_name: str
    started_at: datetime | None
    map_number: int | None
