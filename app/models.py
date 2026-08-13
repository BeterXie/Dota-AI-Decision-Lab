from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    event,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import JSON_DOCUMENT, Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class CanonicalEvent(Base):
    __tablename__ = "canonical_events"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class CanonicalTeam(Base):
    __tablename__ = "canonical_teams"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class TeamAlias(Base):
    __tablename__ = "team_aliases"
    __table_args__ = (
        UniqueConstraint("canonical_team_id", "normalized_name", name="uq_team_alias_normalized"),
        Index("ix_team_alias_lookup", "normalized_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    canonical_team_id: Mapped[UUID] = mapped_column(
        ForeignKey("canonical_teams.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(255), nullable=False)
    provider: Mapped[str | None] = mapped_column(String(32))


class CanonicalPlayer(Base):
    __tablename__ = "canonical_players"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    account_id: Mapped[int | None] = mapped_column(BigInteger, unique=True)
    name: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class CanonicalHero(Base):
    __tablename__ = "canonical_heroes"

    hero_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str | None] = mapped_column(String(255))


class CanonicalSeries(Base):
    __tablename__ = "canonical_series"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    event_id: Mapped[UUID | None] = mapped_column(ForeignKey("canonical_events.id"))
    team_a_id: Mapped[UUID] = mapped_column(ForeignKey("canonical_teams.id"), nullable=False)
    team_b_id: Mapped[UUID] = mapped_column(ForeignKey("canonical_teams.id"), nullable=False)
    best_of: Mapped[int | None] = mapped_column(Integer)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class CanonicalMap(Base):
    __tablename__ = "canonical_maps"
    __table_args__ = (
        UniqueConstraint("series_id", "map_number", name="uq_canonical_maps_series_map"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    series_id: Mapped[UUID | None] = mapped_column(ForeignKey("canonical_series.id"))
    map_number: Mapped[int | None] = mapped_column(Integer)
    valve_match_id: Mapped[int | None] = mapped_column(BigInteger, unique=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ProviderTeamMapping(Base):
    __tablename__ = "provider_team_mappings"
    __table_args__ = (
        UniqueConstraint("provider", "provider_team_id", name="uq_provider_team_identity"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_team_id: Mapped[str] = mapped_column(String(128), nullable=False)
    canonical_team_id: Mapped[UUID] = mapped_column(
        ForeignKey("canonical_teams.id"), nullable=False
    )
    observed_name: Mapped[str | None] = mapped_column(String(255))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ProviderEventMapping(Base):
    __tablename__ = "provider_event_mappings"
    __table_args__ = (
        UniqueConstraint("provider", "provider_event_id", name="uq_provider_event_identity"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    canonical_event_id: Mapped[UUID] = mapped_column(
        ForeignKey("canonical_events.id"), nullable=False
    )
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ProviderPlayerMapping(Base):
    __tablename__ = "provider_player_mappings"
    __table_args__ = (
        UniqueConstraint("provider", "provider_player_id", name="uq_provider_player_identity"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_player_id: Mapped[str] = mapped_column(String(128), nullable=False)
    canonical_player_id: Mapped[UUID] = mapped_column(
        ForeignKey("canonical_players.id"), nullable=False
    )
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ProviderHeroMapping(Base):
    __tablename__ = "provider_hero_mappings"
    __table_args__ = (
        UniqueConstraint("provider", "provider_hero_id", name="uq_provider_hero_identity"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_hero_id: Mapped[str] = mapped_column(String(128), nullable=False)
    canonical_hero_id: Mapped[int] = mapped_column(
        ForeignKey("canonical_heroes.hero_id"), nullable=False
    )
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ProviderMatchMapping(Base):
    __tablename__ = "provider_match_mappings"
    __table_args__ = (
        UniqueConstraint("provider", "provider_match_id", name="uq_provider_match_identity"),
        Index("ix_provider_match_valve_id", "valve_match_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_match_id: Mapped[str] = mapped_column(String(128), nullable=False)
    canonical_series_id: Mapped[UUID | None] = mapped_column(ForeignKey("canonical_series.id"))
    canonical_map_id: Mapped[UUID | None] = mapped_column(ForeignKey("canonical_maps.id"))
    valve_match_id: Mapped[int | None] = mapped_column(BigInteger)
    resolved_by: Mapped[str] = mapped_column(String(64), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ProviderRawEvent(Base):
    __tablename__ = "provider_raw_events"
    __table_args__ = (
        Index("ix_raw_provider_key_received", "provider", "provider_key", "received_at"),
        Index("ix_raw_received_brin", "received_at", postgresql_using="brin"),
        {"postgresql_partition_by": "RANGE (received_at)"},
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_key: Mapped[str | None] = mapped_column(String(255))
    request_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provider_event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, nullable=False
    )
    stored_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    payload: Mapped[dict] = mapped_column(JSON_DOCUMENT, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(32), nullable=False)
    connection_id: Mapped[str | None] = mapped_column(String(64))
    reconnect_generation: Mapped[int | None] = mapped_column(Integer)
    normalized_state_hash: Mapped[str | None] = mapped_column(String(128))
    is_duplicate: Mapped[bool | None] = mapped_column(Boolean)


class RayBetMatch(Base):
    __tablename__ = "raybet_matches"
    __table_args__ = (Index("ix_raybet_match_observed", "provider_match_id", "observed_at"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    provider_match_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    game_id: Mapped[int] = mapped_column(Integer, nullable=False)
    tournament_id: Mapped[int | None] = mapped_column(BigInteger)
    tournament_name: Mapped[str | None] = mapped_column(String(255))
    team_a_provider_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    team_a_name: Mapped[str] = mapped_column(String(255), nullable=False)
    team_b_provider_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    team_b_name: Mapped[str] = mapped_column(String(255), nullable=False)
    round: Mapped[str | None] = mapped_column(String(64))
    raw_status: Mapped[int | None] = mapped_column(Integer)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    raw_event_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)


class RayBetOddsRegistry(Base):
    __tablename__ = "raybet_odds_registry"

    odds_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    provider_match_id: Mapped[int] = mapped_column(BigInteger, index=True)
    team_id: Mapped[int | None] = mapped_column(BigInteger)
    team_name: Mapped[str | None] = mapped_column(String(255))
    group_short_name: Mapped[str | None] = mapped_column(String(128))
    match_stage: Mapped[str | None] = mapped_column(String(64))
    raw_status: Mapped[int | None] = mapped_column(Integer)
    refreshed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    raw_event_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)


class OddsObservationRecord(Base):
    __tablename__ = "odds_observations"
    __table_args__ = (
        Index("ix_odds_map_received", "canonical_map_id", "received_at"),
        Index("ix_odds_id_provider_time", "odds_id", "provider_updated_at"),
        Index("ix_odds_received_brin", "received_at", postgresql_using="brin"),
        {"postgresql_partition_by": "RANGE (received_at)"},
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    provider: Mapped[str] = mapped_column(String(32), default="raybet")
    provider_match_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    odds_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    canonical_series_id: Mapped[UUID | None] = mapped_column(ForeignKey("canonical_series.id"))
    canonical_map_id: Mapped[UUID | None] = mapped_column(ForeignKey("canonical_maps.id"))
    market_type: Mapped[str | None] = mapped_column(String(128))
    match_stage: Mapped[str | None] = mapped_column(String(64))
    selection_team_id: Mapped[UUID | None] = mapped_column(ForeignKey("canonical_teams.id"))
    price: Mapped[Decimal] = mapped_column(Numeric(12, 5), nullable=False)
    implied_probability: Mapped[float] = mapped_column(Float, nullable=False)
    fair_probability: Mapped[float | None] = mapped_column(Float)
    overround: Mapped[float | None] = mapped_column(Float)
    raw_status: Mapped[int | None] = mapped_column(Integer)
    normalized_status: Mapped[str | None] = mapped_column(String(32))
    metadata_version: Mapped[str | None] = mapped_column(String(64))
    provider_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, nullable=False
    )
    stored_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    raw_event_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)


class DraftSnapshotRecord(Base):
    __tablename__ = "draft_snapshots"
    __table_args__ = (Index("ix_draft_map_cutoff", "canonical_map_id", "statistics_cutoff"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    canonical_map_id: Mapped[UUID] = mapped_column(ForeignKey("canonical_maps.id"), nullable=False)
    valve_match_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    complete: Mapped[bool] = mapped_column(Boolean, nullable=False)
    blockers: Mapped[list] = mapped_column(JSON_DOCUMENT, nullable=False)
    warnings: Mapped[list] = mapped_column(JSON_DOCUMENT, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    statistics_cutoff: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    raw_event_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)


class DraftSlotRecord(Base):
    __tablename__ = "draft_slots"
    __table_args__ = (
        UniqueConstraint("draft_snapshot_id", "side", "position", name="uq_draft_side_position"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    draft_snapshot_id: Mapped[UUID] = mapped_column(
        ForeignKey("draft_snapshots.id"), nullable=False
    )
    side: Mapped[str] = mapped_column(String(16), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    account_id: Mapped[int | None] = mapped_column(BigInteger)
    canonical_player_id: Mapped[UUID | None] = mapped_column(ForeignKey("canonical_players.id"))
    hero_id: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)


class DraftMinuteCurveRecord(Base):
    __tablename__ = "draft_minute_curves"
    __table_args__ = (
        UniqueConstraint(
            "draft_snapshot_id", "model_version", name="uq_draft_curve_snapshot_model"
        ),
        Index("ix_draft_curve_map_cutoff", "canonical_map_id", "statistics_cutoff"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    canonical_map_id: Mapped[UUID] = mapped_column(ForeignKey("canonical_maps.id"), nullable=False)
    draft_snapshot_id: Mapped[UUID] = mapped_column(
        ForeignKey("draft_snapshots.id"), nullable=False
    )
    points: Mapped[list] = mapped_column(JSON_DOCUMENT, nullable=False)
    derived_features: Mapped[dict] = mapped_column(JSON_DOCUMENT, nullable=False)
    statistics_cutoff: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    data_version: Mapped[str] = mapped_column(String(64), nullable=False)


class HistoricalMapRecord(Base):
    __tablename__ = "historical_maps"
    __table_args__ = (
        UniqueConstraint("provider", "provider_match_id", name="uq_historical_provider_match"),
        Index("ix_historical_map_usable", "first_usable_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    canonical_map_id: Mapped[UUID | None] = mapped_column(ForeignKey("canonical_maps.id"))
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_match_id: Mapped[str] = mapped_column(String(128), nullable=False)
    patch_id: Mapped[str | None] = mapped_column(String(64))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    radiant_team_id: Mapped[UUID | None] = mapped_column(ForeignKey("canonical_teams.id"))
    dire_team_id: Mapped[UUID | None] = mapped_column(ForeignKey("canonical_teams.id"))
    winner_team_id: Mapped[UUID | None] = mapped_column(ForeignKey("canonical_teams.id"))
    first_usable_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    normalizer_version: Mapped[str | None] = mapped_column(String(64))
    basic_ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    advanced_ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sync_status: Mapped[str] = mapped_column(String(32), nullable=False)
    raw_event_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)


class HistoricalPlayerMapRecord(Base):
    __tablename__ = "historical_player_maps"
    __table_args__ = (
        UniqueConstraint("historical_map_id", "account_id", name="uq_historical_map_player"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    historical_map_id: Mapped[UUID] = mapped_column(
        ForeignKey("historical_maps.id"), nullable=False
    )
    canonical_player_id: Mapped[UUID | None] = mapped_column(ForeignKey("canonical_players.id"))
    account_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    canonical_team_id: Mapped[UUID | None] = mapped_column(ForeignKey("canonical_teams.id"))
    opponent_team_id: Mapped[UUID | None] = mapped_column(ForeignKey("canonical_teams.id"))
    hero_id: Mapped[int] = mapped_column(Integer, nullable=False)
    position: Mapped[int | None] = mapped_column(Integer)
    won: Mapped[bool] = mapped_column(Boolean, nullable=False)
    kills: Mapped[int | None] = mapped_column(Integer)
    deaths: Mapped[int | None] = mapped_column(Integer)
    assists: Mapped[int | None] = mapped_column(Integer)
    gpm: Mapped[float | None] = mapped_column(Float)
    xpm: Mapped[float | None] = mapped_column(Float)
    networth: Mapped[float | None] = mapped_column(Float)
    last_hits: Mapped[int | None] = mapped_column(Integer)
    hero_damage: Mapped[float | None] = mapped_column(Float)
    tower_damage: Mapped[float | None] = mapped_column(Float)
    impact: Mapped[float | None] = mapped_column(Float)
    basic_first_usable_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    advanced_first_usable_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RoleMetricBaselineRecord(Base):
    __tablename__ = "role_metric_baselines"
    __table_args__ = (
        UniqueConstraint(
            "patch_id", "position", "metric", "knowledge_cutoff", name="uq_role_baseline_cutoff"
        ),
        Index("ix_role_baseline_asof", "patch_id", "position", "knowledge_cutoff"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    patch_id: Mapped[str] = mapped_column(String(64), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    metric: Mapped[str] = mapped_column(String(64), nullable=False)
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False)
    mean: Mapped[float | None] = mapped_column(Float)
    std: Mapped[float | None] = mapped_column(Float)
    median: Mapped[float | None] = mapped_column(Float)
    p25: Mapped[float | None] = mapped_column(Float)
    p75: Mapped[float | None] = mapped_column(Float)
    knowledge_cutoff: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class TeamRatingSnapshotRecord(Base):
    __tablename__ = "team_rating_snapshots"
    __table_args__ = (
        UniqueConstraint("canonical_team_id", "source_map_id", name="uq_team_rating_source"),
        Index("ix_team_rating_asof", "canonical_team_id", "knowledge_cutoff"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    canonical_team_id: Mapped[UUID] = mapped_column(
        ForeignKey("canonical_teams.id"), nullable=False
    )
    rating: Mapped[float] = mapped_column(Float, nullable=False)
    rating_before: Mapped[float] = mapped_column(Float, nullable=False)
    opponent_rating_before: Mapped[float] = mapped_column(Float, nullable=False)
    expected_probability: Mapped[float] = mapped_column(Float, nullable=False)
    result: Mapped[float] = mapped_column(Float, nullable=False)
    source_map_id: Mapped[UUID] = mapped_column(ForeignKey("historical_maps.id"), nullable=False)
    knowledge_cutoff: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)


class TeamFormSnapshotRecord(Base):
    __tablename__ = "team_form_snapshots"
    __table_args__ = (Index("ix_team_form_asof", "canonical_team_id", "knowledge_cutoff"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    canonical_team_id: Mapped[UUID] = mapped_column(
        ForeignKey("canonical_teams.id"), nullable=False
    )
    last_5_maps: Mapped[int] = mapped_column(Integer, nullable=False)
    last_5_wins: Mapped[int] = mapped_column(Integer, nullable=False)
    last_10_maps: Mapped[int] = mapped_column(Integer, nullable=False)
    last_10_wins: Mapped[int] = mapped_column(Integer, nullable=False)
    last_20_maps: Mapped[int] = mapped_column(Integer, nullable=False)
    last_20_wins: Mapped[int] = mapped_column(Integer, nullable=False)
    recent_form: Mapped[float | None] = mapped_column(Float)
    exact_roster_maps: Mapped[int] = mapped_column(Integer, nullable=False)
    roster_stability: Mapped[float | None] = mapped_column(Float)
    knowledge_cutoff: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)


class PlayerPerformanceMapRecord(Base):
    __tablename__ = "player_performance_maps"
    __table_args__ = (
        UniqueConstraint(
            "canonical_player_id",
            "canonical_map_id",
            "knowledge_cutoff",
            "model_version",
            name="uq_player_performance_version",
        ),
        Index("ix_player_performance_asof", "canonical_player_id", "knowledge_cutoff"),
        Index("ix_player_performance_source", "source_historical_player_map_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    canonical_player_id: Mapped[UUID] = mapped_column(
        ForeignKey("canonical_players.id"), nullable=False
    )
    canonical_map_id: Mapped[UUID] = mapped_column(ForeignKey("canonical_maps.id"), nullable=False)
    source_historical_player_map_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("historical_player_maps.id")
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    metric_payload: Mapped[dict] = mapped_column(JSON_DOCUMENT, nullable=False)
    role_adjusted_score: Mapped[float | None] = mapped_column(Float)
    knowledge_cutoff: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)


class PlayerFormSnapshotRecord(Base):
    __tablename__ = "player_form_snapshots"
    __table_args__ = (
        Index("ix_player_form_asof", "canonical_player_id", "position", "knowledge_cutoff"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    canonical_player_id: Mapped[UUID] = mapped_column(
        ForeignKey("canonical_players.id"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    base_strength: Mapped[float | None] = mapped_column(Float)
    recent_5: Mapped[float | None] = mapped_column(Float)
    recent_10: Mapped[float | None] = mapped_column(Float)
    recent_20: Mapped[float | None] = mapped_column(Float)
    recent_form: Mapped[float | None] = mapped_column(Float)
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    last_included_map_id: Mapped[UUID | None] = mapped_column(ForeignKey("canonical_maps.id"))
    knowledge_cutoff: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)


class PlayerHeroSnapshotRecord(Base):
    __tablename__ = "player_hero_snapshots"
    __table_args__ = (
        Index(
            "ix_player_hero_asof",
            "canonical_player_id",
            "hero_id",
            "position",
            "knowledge_cutoff",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    canonical_player_id: Mapped[UUID] = mapped_column(
        ForeignKey("canonical_players.id"), nullable=False
    )
    hero_id: Mapped[int] = mapped_column(Integer, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    historical_maps: Mapped[int] = mapped_column(Integer, nullable=False)
    historical_win_rate: Mapped[float | None] = mapped_column(Float)
    historical_performance: Mapped[float | None] = mapped_column(Float)
    recent_180d_maps: Mapped[int] = mapped_column(Integer, nullable=False)
    recent_180d_win_rate: Mapped[float | None] = mapped_column(Float)
    recent_180d_performance: Mapped[float | None] = mapped_column(Float)
    current_patch_maps: Mapped[int] = mapped_column(Integer, nullable=False)
    current_patch_win_rate: Mapped[float | None] = mapped_column(Float)
    current_patch_performance: Mapped[float | None] = mapped_column(Float)
    position_fit: Mapped[float | None] = mapped_column(Float)
    raw_strength: Mapped[float | None] = mapped_column(Float)
    adjusted_strength: Mapped[float | None] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    last_included_map_id: Mapped[UUID | None] = mapped_column(ForeignKey("canonical_maps.id"))
    knowledge_cutoff: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)


class FeatureSnapshotSource(Base):
    __tablename__ = "feature_snapshot_sources"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    feature_type: Mapped[str] = mapped_column(String(64), nullable=False)
    feature_snapshot_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_match_id: Mapped[str] = mapped_column(String(128), nullable=False)
    raw_event_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    first_usable_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DltvLiveObservationRecord(Base):
    __tablename__ = "dltv_live_observations"
    __table_args__ = (
        UniqueConstraint(
            "valve_match_id", "payload_hash", "received_at", name="uq_dltv_normalized_state"
        ),
        Index("ix_dltv_map_received", "canonical_map_id", "received_at"),
        Index("ix_dltv_received_brin", "received_at", postgresql_using="brin"),
        {"postgresql_partition_by": "RANGE (received_at)"},
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    canonical_map_id: Mapped[UUID | None] = mapped_column(ForeignKey("canonical_maps.id"))
    valve_match_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    game_time_seconds: Mapped[int | None] = mapped_column(Integer)
    radiant_kills: Mapped[int | None] = mapped_column(Integer)
    dire_kills: Mapped[int | None] = mapped_column(Integer)
    radiant_nw_lead: Mapped[int | None] = mapped_column(Integer)
    first_blood: Mapped[str | None] = mapped_column(String(32))
    source_game_time: Mapped[int | None] = mapped_column(Integer)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, nullable=False
    )
    stored_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    payload_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    connection_id: Mapped[str | None] = mapped_column(String(64))
    reconnect_generation: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_message_received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    last_state_change_received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    raw_event_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)


class LiveSyncEstimateRecord(Base):
    __tablename__ = "live_sync_estimates"
    __table_args__ = (Index("ix_live_sync_map_time", "canonical_map_id", "calculated_at"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    canonical_map_id: Mapped[UUID] = mapped_column(ForeignKey("canonical_maps.id"), nullable=False)
    estimated_lag_seconds: Mapped[float | None] = mapped_column(Float)
    p50_seconds: Mapped[float | None] = mapped_column(Float)
    p90_seconds: Mapped[float | None] = mapped_column(Float)
    jitter_seconds: Mapped[float | None] = mapped_column(Float)
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False)
    accepted_pair_ratio: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    ambiguous_ratio: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    outlier_ratio: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    confidence: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class LiveCalibrationPairRecord(Base):
    __tablename__ = "live_calibration_pairs"
    __table_args__ = (
        UniqueConstraint(
            "canonical_map_id",
            "calculated_at",
            "raybet_signal_id",
            name="uq_live_calibration_signal",
        ),
        Index("ix_live_calibration_map_time", "canonical_map_id", "calculated_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    canonical_map_id: Mapped[UUID] = mapped_column(ForeignKey("canonical_maps.id"), nullable=False)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    raybet_signal_id: Mapped[str] = mapped_column(String(128), nullable=False)
    dltv_signal_id: Mapped[str | None] = mapped_column(String(128))
    raybet_received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    dltv_received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lag_seconds: Mapped[float | None] = mapped_column(Float)
    raybet_signal_type: Mapped[str] = mapped_column(String(64), nullable=False)
    dltv_signal_type: Mapped[str | None] = mapped_column(String(64))
    uniqueness_margin_seconds: Mapped[float | None] = mapped_column(Float)
    accepted: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reject_reason: Mapped[str | None] = mapped_column(String(64))


class DecisionSnapshotRecord(Base):
    __tablename__ = "decision_snapshots"
    __table_args__ = (Index("ix_decision_map_time", "canonical_map_id", "decision_at"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    canonical_map_id: Mapped[UUID | None] = mapped_column(ForeignKey("canonical_maps.id"))
    decision_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    canonical_payload: Mapped[dict] = mapped_column(JSON_DOCUMENT, nullable=False)
    snapshot_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)


class AiDecisionRecord(Base):
    __tablename__ = "ai_decisions"
    __table_args__ = (
        UniqueConstraint(
            "snapshot_id",
            "provider",
            "model",
            "prompt_version",
            "decision_policy_version",
            name="uq_ai_experiment",
        ),
        Index("ix_ai_snapshot_provider", "snapshot_hash", "provider"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    snapshot_id: Mapped[UUID] = mapped_column(ForeignKey("decision_snapshots.id"), nullable=False)
    snapshot_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    model_version: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    decision_policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    request_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    response_received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    latency_seconds: Mapped[float | None] = mapped_column(Float)
    raw_response: Mapped[dict | None] = mapped_column(JSON_DOCUMENT)
    normalized_response: Mapped[dict | None] = mapped_column(JSON_DOCUMENT)
    parse_status: Mapped[str] = mapped_column(String(32), nullable=False)
    error: Mapped[str | None] = mapped_column(Text)


class DecisionEmailNotificationRecord(Base):
    __tablename__ = "decision_email_notifications"
    __table_args__ = (
        UniqueConstraint(
            "snapshot_id",
            "decision_batch_key",
            name="uq_decision_email_snapshot_batch",
        ),
        UniqueConstraint("idempotency_key", name="uq_decision_email_idempotency_key"),
        Index("ix_decision_email_status_created", "status", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    snapshot_id: Mapped[UUID] = mapped_column(ForeignKey("decision_snapshots.id"), nullable=False)
    snapshot_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    decision_batch_key: Mapped[str] = mapped_column(String(255), nullable=False)
    sender: Mapped[str] = mapped_column(String(320), nullable=False)
    recipients: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, nullable=False)
    subject: Mapped[str] = mapped_column(String(512), nullable=False)
    text_body: Mapped[str] = mapped_column(Text, nullable=False)
    html_body: Mapped[str] = mapped_column(Text, nullable=False)
    template_version: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    provider_message_id: Mapped[str | None] = mapped_column(String(255))
    translation_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="DISABLED"
    )
    translation_model: Mapped[str | None] = mapped_column(String(128))
    translation_raw_response: Mapped[dict | None] = mapped_column(JSON_DOCUMENT)
    translation_error: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class DecisionFutureOdds(Base):
    __tablename__ = "decision_future_odds"
    __table_args__ = (
        UniqueConstraint(
            "decision_snapshot_id", "capture_type", "due_at", name="uq_future_odds_capture"
        ),
        Index("ix_future_odds_due_brin", "due_at", postgresql_using="brin"),
        {"postgresql_partition_by": "RANGE (due_at)"},
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    decision_snapshot_id: Mapped[UUID] = mapped_column(
        ForeignKey("decision_snapshots.id"), nullable=False
    )
    capture_type: Mapped[str] = mapped_column(String(32), nullable=False)
    horizon_seconds: Mapped[int | None] = mapped_column(Integer)
    triggered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    odds_a: Mapped[Decimal | None] = mapped_column(Numeric(12, 5))
    odds_b: Mapped[Decimal | None] = mapped_column(Numeric(12, 5))
    market_type: Mapped[str | None] = mapped_column(String(128))
    match_stage: Mapped[str | None] = mapped_column(String(64))
    market_status: Mapped[str | None] = mapped_column(String(32))
    capture_policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    pair_quality: Mapped[dict] = mapped_column(JSON_DOCUMENT, nullable=False, default=dict)
    pair_skew_seconds: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(32), nullable=False)


class MapResultRecord(Base):
    __tablename__ = "map_results"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    canonical_map_id: Mapped[UUID] = mapped_column(ForeignKey("canonical_maps.id"), unique=True)
    winner_team_id: Mapped[UUID | None] = mapped_column(ForeignKey("canonical_teams.id"))
    basic_first_usable_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    advanced_first_usable_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    settled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    provider_conflict: Mapped[bool] = mapped_column(Boolean, default=False)


class MapResultEvidenceRecord(Base):
    __tablename__ = "map_result_evidence"
    __table_args__ = (
        UniqueConstraint("canonical_map_id", "raw_event_id", name="uq_result_evidence_raw"),
        Index("ix_result_evidence_map_usable", "canonical_map_id", "first_usable_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    canonical_map_id: Mapped[UUID] = mapped_column(ForeignKey("canonical_maps.id"), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_match_id: Mapped[str] = mapped_column(String(128), nullable=False)
    winner_team_id: Mapped[UUID | None] = mapped_column(ForeignKey("canonical_teams.id"))
    result_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    first_usable_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    raw_event_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    normalizer_version: Mapped[str] = mapped_column(String(64), nullable=False)
    identity_confidence: Mapped[float] = mapped_column(Float, nullable=False)
    conflict_status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class DecisionEvaluationRecord(Base):
    __tablename__ = "decision_evaluations"
    __table_args__ = (UniqueConstraint("ai_decision_id", name="uq_evaluation_ai_decision"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    ai_decision_id: Mapped[UUID] = mapped_column(ForeignKey("ai_decisions.id"), nullable=False)
    result_correct: Mapped[bool | None] = mapped_column(Boolean)
    brier_score: Mapped[float | None] = mapped_column(Float)
    log_loss: Mapped[float | None] = mapped_column(Float)
    clv: Mapped[float | None] = mapped_column(Float)
    future_odds_direction: Mapped[str | None] = mapped_column(String(32))
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    metrics_version: Mapped[str] = mapped_column(String(64), nullable=False)


class DomainEventRecord(Base):
    __tablename__ = "domain_events"
    __table_args__ = (
        UniqueConstraint("event_type", "dedupe_key", name="uq_domain_event_dedupe"),
        Index("ix_domain_event_pending", "processed_at", "occurred_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(64), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(128), nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(255), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON_DOCUMENT, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DurableJobRecord(Base):
    __tablename__ = "durable_jobs"
    __table_args__ = (
        UniqueConstraint("job_type", "dedupe_key", name="uq_durable_job_dedupe"),
        Index("ix_durable_job_claim", "status", "priority", "not_before"),
        Index("ix_durable_job_lease", "status", "locked_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    job_type: Mapped[str] = mapped_column(String(64), nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(255), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON_DOCUMENT, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING")
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    not_before: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=8)
    locked_by: Mapped[str | None] = mapped_column(String(128))
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class JobAttemptRecord(Base):
    __tablename__ = "job_attempts"
    __table_args__ = (
        UniqueConstraint("job_id", "attempt_number", name="uq_job_attempt_number"),
        Index("ix_job_attempt_started", "job_id", "started_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    job_id: Mapped[UUID] = mapped_column(ForeignKey("durable_jobs.id"), nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    worker_id: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)


class WorkerCheckpointRecord(Base):
    __tablename__ = "worker_checkpoints"

    worker_name: Mapped[str] = mapped_column(String(128), primary_key=True)
    checkpoint: Mapped[dict] = mapped_column(JSON_DOCUMENT, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class OutboxEventRecord(Base):
    __tablename__ = "outbox_events"
    __table_args__ = (
        UniqueConstraint("domain_event_id", "topic", name="uq_outbox_event_topic"),
        Index("ix_outbox_pending", "published_at", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    domain_event_id: Mapped[UUID] = mapped_column(ForeignKey("domain_events.id"), nullable=False)
    topic: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON_DOCUMENT, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)


def _immutable_snapshot(*_args: object, **_kwargs: object) -> None:
    raise ValueError("DecisionSnapshot records are immutable")


event.listen(DecisionSnapshotRecord, "before_update", _immutable_snapshot)
event.listen(DecisionSnapshotRecord, "before_delete", _immutable_snapshot)
