from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models import utc_now


class TeamProfile(Base):
    __tablename__ = "team_profiles"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_team_profiles_slug"),
        UniqueConstraint("valve_team_id", name="uq_team_profiles_valve_team_id"),
    )

    canonical_team_id: Mapped[UUID] = mapped_column(
        ForeignKey("canonical_teams.id", ondelete="CASCADE"), primary_key=True
    )
    slug: Mapped[str | None] = mapped_column(String(160))
    short_name: Mapped[str | None] = mapped_column(String(64))
    valve_team_id: Mapped[int | None] = mapped_column(BigInteger)
    country_code: Mapped[str | None] = mapped_column(String(2))
    logo_url: Mapped[str | None] = mapped_column(Text)
    logo_source: Mapped[str | None] = mapped_column(String(64))
    website_url: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text)
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class PlayerProfile(Base):
    __tablename__ = "player_profiles"
    __table_args__ = (UniqueConstraint("slug", name="uq_player_profiles_slug"),)

    canonical_player_id: Mapped[UUID] = mapped_column(
        ForeignKey("canonical_players.id", ondelete="CASCADE"), primary_key=True
    )
    slug: Mapped[str | None] = mapped_column(String(160))
    real_name: Mapped[str | None] = mapped_column(String(255))
    country_code: Mapped[str | None] = mapped_column(String(2))
    avatar_url: Mapped[str | None] = mapped_column(Text)
    avatar_source: Mapped[str | None] = mapped_column(String(64))
    source_url: Mapped[str | None] = mapped_column(Text)
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class CanonicalStaff(Base):
    __tablename__ = "canonical_staff"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    real_name: Mapped[str | None] = mapped_column(String(255))
    country_code: Mapped[str | None] = mapped_column(String(2))
    avatar_url: Mapped[str | None] = mapped_column(Text)
    avatar_source: Mapped[str | None] = mapped_column(String(64))
    source_url: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class TeamRosterMembership(Base):
    __tablename__ = "team_roster_memberships"
    __table_args__ = (
        CheckConstraint(
            "(player_id IS NOT NULL AND staff_id IS NULL) OR "
            "(player_id IS NULL AND staff_id IS NOT NULL)",
            name="roster_member_exactly_one_subject",
        ),
        CheckConstraint(
            "position IS NULL OR (position >= 1 AND position <= 5)",
            name="roster_position_range",
        ),
        CheckConstraint(
            "valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from",
            name="roster_valid_range",
        ),
        Index("ix_team_roster_team_active", "team_id", "valid_to"),
        Index("ix_team_roster_player_timeline", "player_id", "valid_from", "valid_to"),
        Index("ix_team_roster_staff_timeline", "staff_id", "valid_from", "valid_to"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    team_id: Mapped[UUID] = mapped_column(
        ForeignKey("canonical_teams.id", ondelete="CASCADE"), nullable=False
    )
    player_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("canonical_players.id", ondelete="CASCADE")
    )
    staff_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("canonical_staff.id", ondelete="CASCADE")
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    position: Mapped[int | None] = mapped_column(Integer)
    is_standin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_name: Mapped[str] = mapped_column(String(64), nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
