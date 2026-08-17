from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class BillingSubscriptionRecord(Base):
    __tablename__ = "billing_subscriptions"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "subscription_ref",
            name="uq_billing_subscriptions_provider_ref",
        ),
        Index("ix_billing_subscriptions_user_status", "user_id", "access_state"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    subscription_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    customer_ref: Mapped[str | None] = mapped_column(String(160))
    plan_key: Mapped[str] = mapped_column(String(64), nullable=False)
    access_state: Mapped[str] = mapped_column(String(16), nullable=False)
    provider_status: Mapped[str | None] = mapped_column(String(64))
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_event_occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class BillingEventRecord(Base):
    __tablename__ = "billing_events"
    __table_args__ = (
        UniqueConstraint("provider", "event_ref", name="uq_billing_events_provider_ref"),
        Index("ix_billing_events_subscription", "provider", "subscription_ref"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    event_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    subscription_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
