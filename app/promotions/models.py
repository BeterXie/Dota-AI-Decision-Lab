from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class ReferralCodeRecord(Base):
    __tablename__ = "referral_codes"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_referral_codes_user"),
        UniqueConstraint("code", name="uq_referral_codes_code"),
        Index("ix_referral_codes_status", "status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class ReferralAttributionRecord(Base):
    __tablename__ = "referral_attributions"
    __table_args__ = (
        UniqueConstraint("invited_user_id", name="uq_referral_attributions_invited_user"),
        UniqueConstraint(
            "qualified_provider",
            "qualified_payment_ref",
            name="uq_referral_attributions_payment",
        ),
        Index("ix_referral_attributions_inviter", "inviter_user_id", "status"),
        Index("ix_referral_attributions_campaign", "campaign_key", "status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    inviter_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False
    )
    invited_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False
    )
    referral_code_id: Mapped[UUID] = mapped_column(
        ForeignKey("referral_codes.id", ondelete="RESTRICT"), nullable=False
    )
    campaign_key: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="CLAIMED")
    qualified_provider: Mapped[str | None] = mapped_column(String(32))
    qualified_payment_ref: Mapped[str | None] = mapped_column(String(160))
    claimed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    qualified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rewarded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class SeriesPassPurchaseRecord(Base):
    """Server-owned mapping for one Paddle purchase of one canonical series."""

    __tablename__ = "series_pass_purchases"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "transaction_ref",
            name="uq_series_pass_purchases_provider_transaction",
        ),
        Index(
            "ix_series_pass_purchases_user_series",
            "user_id",
            "canonical_series_id",
            "status",
        ),
        Index("ix_series_pass_purchases_customer", "provider", "customer_ref"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    transaction_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    customer_ref: Mapped[str | None] = mapped_column(String(160))
    canonical_series_id: Mapped[UUID] = mapped_column(
        ForeignKey("canonical_series.id", ondelete="CASCADE"), nullable=False
    )
    price_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")
    payment_blocked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    grant_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_event_occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class SeriesPassEventRecord(Base):
    __tablename__ = "series_pass_events"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "event_ref",
            name="uq_series_pass_events_provider_ref",
        ),
        Index("ix_series_pass_events_transaction", "provider", "transaction_ref"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    event_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    transaction_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False
    )
    canonical_series_id: Mapped[UUID] = mapped_column(
        ForeignKey("canonical_series.id", ondelete="CASCADE"), nullable=False
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    applied: Mapped[bool] = mapped_column(Boolean, nullable=False)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
