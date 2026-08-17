from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class UserAccountRecord(Base):
    __tablename__ = "user_accounts"
    __table_args__ = (UniqueConstraint("email", name="uq_user_accounts_email"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    # Steam OpenID does not expose an email address. Keep the account usable
    # without inventing a fake inbox; users can later attach a verified email.
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    email_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    display_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_login_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ExternalIdentityRecord(Base):
    __tablename__ = "external_identities"
    __table_args__ = (
        UniqueConstraint("provider", "subject", name="uq_external_identity_provider_subject"),
        Index("ix_external_identity_user", "user_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    provider_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_login_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class EmailLoginChallengeRecord(Base):
    __tablename__ = "email_login_challenges"
    __table_args__ = (
        Index("ix_email_login_challenge_email_created", "email", "created_at"),
        Index("ix_email_login_challenge_expiry", "expires_at", "consumed_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    code_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivery_status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AuthSessionRecord(Base):
    __tablename__ = "auth_sessions"
    __table_args__ = (
        UniqueConstraint("token_digest", name="uq_auth_sessions_token_digest"),
        Index("ix_auth_session_user_expiry", "user_id", "expires_at"),
        Index("ix_auth_session_expiry_revoked", "expires_at", "revoked_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False
    )
    token_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
