from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import JSON_DOCUMENT, Base
from app.models import utc_now


class RuntimeSettingRecord(Base):
    __tablename__ = "runtime_settings"

    key: Mapped[str] = mapped_column(String(160), primary_key=True)
    value: Mapped[object] = mapped_column(JSON_DOCUMENT, nullable=False)
    value_type: Mapped[str] = mapped_column(String(24), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_by: Mapped[str | None] = mapped_column(String(320))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class RuntimeSecretRecord(Base):
    __tablename__ = "runtime_secrets"

    key: Mapped[str] = mapped_column(String(160), primary_key=True)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_by: Mapped[str | None] = mapped_column(String(320))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AiProviderConfigRecord(Base):
    __tablename__ = "ai_provider_configs"
    __table_args__ = (UniqueConstraint("provider", "slot", name="uq_ai_provider_config_slot"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    slot: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    decisions_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    base_url: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(String(160), nullable=False)
    reasoning_effort: Mapped[str | None] = mapped_column(String(32))
    timeout_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    api_key_secret_key: Mapped[str | None] = mapped_column(String(160))
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_by: Mapped[str | None] = mapped_column(String(320))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class RuntimeConfigAuditRecord(Base):
    __tablename__ = "runtime_config_audit"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    target_key: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    operation: Mapped[str] = mapped_column(String(32), nullable=False)
    previous_value: Mapped[object | None] = mapped_column(JSON_DOCUMENT)
    new_value: Mapped[object | None] = mapped_column(JSON_DOCUMENT)
    secret_changed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    actor: Mapped[str | None] = mapped_column(String(320))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
