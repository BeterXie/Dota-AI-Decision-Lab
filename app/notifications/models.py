from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db import JSON_DOCUMENT, Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class NotificationBindingRecord(Base):
    __tablename__ = "notification_bindings"
    __table_args__ = (
        UniqueConstraint("channel", "destination_key", name="uq_notification_binding_destination"),
        Index("ix_notification_binding_user_status", "user_id", "status", "channel"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False
    )
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    destination_key: Mapped[str] = mapped_column(String(512), nullable=False)
    destination: Mapped[dict] = mapped_column(JSON_DOCUMENT, nullable=False)
    label: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE")
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class NotificationPreferenceRecord(Base):
    __tablename__ = "notification_preferences"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "event_type", "channel", name="uq_notification_preference_user_event_channel"
        ),
        Index("ix_notification_preference_lookup", "user_id", "event_type", "channel"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class NotificationPairingCodeRecord(Base):
    __tablename__ = "notification_pairing_codes"
    __table_args__ = (
        UniqueConstraint("code_digest", name="uq_notification_pairing_code_digest"),
        Index("ix_notification_pairing_user_channel", "user_id", "channel", "created_at"),
        Index("ix_notification_pairing_expiry", "expires_at", "consumed_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False
    )
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    code_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class NotificationDeliveryRecord(Base):
    __tablename__ = "notification_deliveries"
    __table_args__ = (
        UniqueConstraint(
            "binding_id",
            "event_type",
            "snapshot_id",
            "decision_batch_key",
            name="uq_notification_delivery_binding_event_batch",
        ),
        UniqueConstraint("idempotency_key", name="uq_notification_delivery_idempotency"),
        Index("ix_notification_delivery_status_created", "status", "created_at"),
        Index("ix_notification_delivery_user_created", "user_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False
    )
    binding_id: Mapped[UUID] = mapped_column(
        ForeignKey("notification_bindings.id", ondelete="CASCADE"), nullable=False
    )
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot_id: Mapped[UUID] = mapped_column(
        ForeignKey("decision_snapshots.id", ondelete="CASCADE"), nullable=False
    )
    decision_batch_key: Mapped[str] = mapped_column(String(64), nullable=False)
    decision_ids: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")
    attempt_count: Mapped[int] = mapped_column(nullable=False, default=0)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provider_message_id: Mapped[str | None] = mapped_column(String(255))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
