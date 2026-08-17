from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class UserEntitlementRecord(Base):
    """One independently revocable access grant.

    Historical rows used this table as a global entitlement ledger. Scope and
    campaign metadata extend the same source-isolated model without creating a
    second authorization system: GLOBAL grants behave exactly as before while
    SERIES/MAP grants unlock only the referenced resource.
    """

    __tablename__ = "user_entitlements"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "entitlement",
            "source",
            name="uq_user_entitlements_user_entitlement_source",
        ),
        CheckConstraint(
            "(scope_type = 'GLOBAL' AND scope_ref IS NULL) OR "
            "(scope_type IN ('SERIES', 'MAP') AND scope_ref IS NOT NULL)",
            name="ck_user_entitlements_scope",
        ),
        Index(
            "ix_user_entitlements_access",
            "user_id",
            "entitlement",
            "status",
        ),
        Index(
            "ix_user_entitlements_scoped_access",
            "user_id",
            "entitlement",
            "scope_type",
            "scope_ref",
            "status",
        ),
        Index("ix_user_entitlements_campaign", "campaign_key", "status"),
        Index("ix_user_entitlements_expiry", "expires_at", "status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False
    )
    entitlement: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE")
    source: Mapped[str] = mapped_column(String(128), nullable=False)
    scope_type: Mapped[str] = mapped_column(String(16), nullable=False, default="GLOBAL")
    scope_ref: Mapped[UUID | None] = mapped_column(Uuid)
    campaign_key: Mapped[str | None] = mapped_column(String(64))
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
