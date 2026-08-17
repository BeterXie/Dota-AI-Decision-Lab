from __future__ import annotations

import hashlib
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.entitlements.models import UserEntitlementRecord
from app.entitlements.service import REALTIME_NOTIFICATIONS_ENTITLEMENT
from app.notifications.models import (
    NotificationBindingRecord,
    NotificationDeliveryRecord,
    NotificationPairingCodeRecord,
    NotificationPreferenceRecord,
)

CHANNEL_EMAIL = "EMAIL"
CHANNEL_QQ = "QQ"
CHANNEL_WECHAT = "WECHAT"
NOTIFICATION_CHANNELS = (CHANNEL_EMAIL, CHANNEL_QQ, CHANNEL_WECHAT)
PAIRABLE_CHANNELS = (CHANNEL_QQ, CHANNEL_WECHAT)
EVENT_AI_DECISION = "AI_DECISION"

_PAIRING_CODE_TTL_SECONDS = 600
_PAIRING_CODE_RE = re.compile(r"[^A-Z0-9]")


class NotificationPairingError(ValueError):
    pass


class NotificationBindingConflict(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class DeliveryTarget:
    delivery_id: UUID
    user_id: UUID
    binding_id: UUID
    channel: str
    destination: dict[str, Any]
    label: str | None
    idempotency_key: str
    snapshot_id: UUID
    decision_ids: tuple[UUID, ...]
    decision_batch_key: str


class NotificationCenterService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def overview(self, user_id: UUID) -> dict:
        async with self._session_factory() as session:
            bindings = list(
                (
                    await session.scalars(
                        select(NotificationBindingRecord)
                        .where(NotificationBindingRecord.user_id == user_id)
                        .order_by(
                            NotificationBindingRecord.channel,
                            NotificationBindingRecord.created_at,
                        )
                    )
                ).all()
            )
            preferences = list(
                (
                    await session.scalars(
                        select(NotificationPreferenceRecord).where(
                            NotificationPreferenceRecord.user_id == user_id,
                            NotificationPreferenceRecord.event_type == EVENT_AI_DECISION,
                        )
                    )
                ).all()
            )
            deliveries = list(
                (
                    await session.scalars(
                        select(NotificationDeliveryRecord)
                        .where(NotificationDeliveryRecord.user_id == user_id)
                        .order_by(NotificationDeliveryRecord.created_at.desc())
                        .limit(20)
                    )
                ).all()
            )
        enabled_by_channel = {item.channel: item.enabled for item in preferences}
        return {
            "required_entitlement": REALTIME_NOTIFICATIONS_ENTITLEMENT,
            "event_type": EVENT_AI_DECISION,
            "bindings": [self.binding_payload(item) for item in bindings],
            "preferences": {
                channel: enabled_by_channel.get(channel, True) for channel in NOTIFICATION_CHANNELS
            },
            "recent_deliveries": [self.delivery_payload(item) for item in deliveries],
        }

    async def ensure_email_binding(
        self,
        *,
        user_id: UUID,
        email: str,
        verified_at: datetime,
    ) -> NotificationBindingRecord:
        normalized = email.strip().lower()
        if not normalized:
            raise ValueError("verified email is required")
        async with self._session_factory() as session, session.begin():
            binding = await self._upsert_verified_binding(
                session,
                user_id=user_id,
                channel=CHANNEL_EMAIL,
                destination_key=normalized,
                destination={"email": normalized},
                label=normalized,
                verified_at=verified_at,
            )
            await self._ensure_preference(session, user_id, CHANNEL_EMAIL, enabled=True)
            return binding

    async def create_pairing_code(
        self,
        user_id: UUID,
        channel: str,
        *,
        ttl_seconds: int = _PAIRING_CODE_TTL_SECONDS,
    ) -> tuple[str, datetime]:
        normalized_channel = normalize_channel(channel)
        if normalized_channel not in PAIRABLE_CHANNELS:
            raise ValueError("pairing is only supported for QQ and WeChat")
        now = datetime.now(UTC)
        expires_at = now + timedelta(seconds=max(60, ttl_seconds))
        code = _format_pairing_code(secrets.token_hex(4).upper())
        digest = _pairing_digest(code)
        async with self._session_factory() as session, session.begin():
            active_codes = list(
                (
                    await session.scalars(
                        select(NotificationPairingCodeRecord).where(
                            NotificationPairingCodeRecord.user_id == user_id,
                            NotificationPairingCodeRecord.channel == normalized_channel,
                            NotificationPairingCodeRecord.consumed_at.is_(None),
                        )
                    )
                ).all()
            )
            for item in active_codes:
                item.consumed_at = now
            session.add(
                NotificationPairingCodeRecord(
                    user_id=user_id,
                    channel=normalized_channel,
                    code_digest=digest,
                    expires_at=expires_at,
                    created_at=now,
                )
            )
        return code, expires_at

    async def consume_pairing_code(
        self,
        *,
        channel: str,
        code: str,
        destination_key: str,
        destination: dict[str, Any],
        label: str | None = None,
    ) -> NotificationBindingRecord:
        normalized_channel = normalize_channel(channel)
        if normalized_channel not in PAIRABLE_CHANNELS:
            raise NotificationPairingError("unsupported pairing channel")
        digest = _pairing_digest(code)
        now = datetime.now(UTC)
        async with self._session_factory() as session, session.begin():
            pairing = await session.scalar(
                select(NotificationPairingCodeRecord)
                .where(
                    NotificationPairingCodeRecord.channel == normalized_channel,
                    NotificationPairingCodeRecord.code_digest == digest,
                    NotificationPairingCodeRecord.consumed_at.is_(None),
                )
                .limit(1)
                .with_for_update()
            )
            if pairing is None or _as_utc(pairing.expires_at) <= now:
                raise NotificationPairingError("pairing code is invalid or expired")
            binding = await self._upsert_verified_binding(
                session,
                user_id=pairing.user_id,
                channel=normalized_channel,
                destination_key=destination_key,
                destination=destination,
                label=label,
                verified_at=now,
            )
            pairing.consumed_at = now
            await self._ensure_preference(
                session,
                pairing.user_id,
                normalized_channel,
                enabled=True,
            )
            return binding

    async def set_preference(self, user_id: UUID, channel: str, *, enabled: bool) -> None:
        normalized_channel = normalize_channel(channel)
        async with self._session_factory() as session, session.begin():
            await self._ensure_preference(
                session,
                user_id,
                normalized_channel,
                enabled=enabled,
                overwrite=True,
            )

    async def set_preference_for_destination(
        self,
        *,
        channel: str,
        destination_key: str,
        enabled: bool,
    ) -> bool:
        normalized_channel = normalize_channel(channel)
        async with self._session_factory() as session, session.begin():
            binding = await session.scalar(
                select(NotificationBindingRecord)
                .where(
                    NotificationBindingRecord.channel == normalized_channel,
                    NotificationBindingRecord.destination_key == destination_key,
                    NotificationBindingRecord.status == "ACTIVE",
                )
                .limit(1)
            )
            if binding is None:
                return False
            await self._ensure_preference(
                session,
                binding.user_id,
                normalized_channel,
                enabled=enabled,
                overwrite=True,
            )
            return True

    async def disable_binding(self, user_id: UUID, binding_id: UUID) -> bool:
        async with self._session_factory() as session, session.begin():
            binding = await session.scalar(
                select(NotificationBindingRecord)
                .where(
                    NotificationBindingRecord.id == binding_id,
                    NotificationBindingRecord.user_id == user_id,
                )
                .limit(1)
                .with_for_update()
            )
            if binding is None:
                return False
            binding.status = "DISABLED"
            binding.updated_at = datetime.now(UTC)
            return True

    async def eligible_bindings(
        self,
        session: AsyncSession,
        channel: str,
        *,
        event_type: str = EVENT_AI_DECISION,
        now: datetime | None = None,
    ) -> list[NotificationBindingRecord]:
        normalized_channel = normalize_channel(channel)
        current = now or datetime.now(UTC)
        bindings = list(
            (
                await session.scalars(
                    select(NotificationBindingRecord).where(
                        NotificationBindingRecord.channel == normalized_channel,
                        NotificationBindingRecord.status == "ACTIVE",
                        NotificationBindingRecord.verified_at.is_not(None),
                    )
                )
            ).all()
        )
        if not bindings:
            return []
        user_ids = {item.user_id for item in bindings}
        entitled_users = set(
            (
                await session.scalars(
                    select(UserEntitlementRecord.user_id)
                    .where(
                        UserEntitlementRecord.user_id.in_(user_ids),
                        UserEntitlementRecord.entitlement == REALTIME_NOTIFICATIONS_ENTITLEMENT,
                        UserEntitlementRecord.status == "ACTIVE",
                        or_(
                            UserEntitlementRecord.starts_at.is_(None),
                            UserEntitlementRecord.starts_at <= current,
                        ),
                        or_(
                            UserEntitlementRecord.expires_at.is_(None),
                            UserEntitlementRecord.expires_at > current,
                        ),
                    )
                    .distinct()
                )
            ).all()
        )
        if not entitled_users:
            return []
        preferences = list(
            (
                await session.scalars(
                    select(NotificationPreferenceRecord).where(
                        NotificationPreferenceRecord.user_id.in_(entitled_users),
                        NotificationPreferenceRecord.event_type == event_type,
                        NotificationPreferenceRecord.channel == normalized_channel,
                    )
                )
            ).all()
        )
        preference_by_user = {item.user_id: item.enabled for item in preferences}
        return [
            item
            for item in bindings
            if item.user_id in entitled_users and preference_by_user.get(item.user_id, True)
        ]

    async def ensure_deliveries(
        self,
        session: AsyncSession,
        *,
        channel: str,
        snapshot_id: UUID,
        decision_ids: list[UUID],
        event_type: str = EVENT_AI_DECISION,
    ) -> list[NotificationDeliveryRecord]:
        normalized_channel = normalize_channel(channel)
        batch_key = decision_batch_key(decision_ids)
        bindings = await self.eligible_bindings(
            session,
            normalized_channel,
            event_type=event_type,
        )
        deliveries: list[NotificationDeliveryRecord] = []
        raw_decision_ids = [str(item) for item in sorted(decision_ids, key=str)]
        for binding in bindings:
            existing = await session.scalar(
                select(NotificationDeliveryRecord).where(
                    NotificationDeliveryRecord.binding_id == binding.id,
                    NotificationDeliveryRecord.event_type == event_type,
                    NotificationDeliveryRecord.snapshot_id == snapshot_id,
                    NotificationDeliveryRecord.decision_batch_key == batch_key,
                )
            )
            if existing is not None:
                deliveries.append(existing)
                continue
            delivery = NotificationDeliveryRecord(
                user_id=binding.user_id,
                binding_id=binding.id,
                channel=normalized_channel,
                event_type=event_type,
                snapshot_id=snapshot_id,
                decision_batch_key=batch_key,
                decision_ids=raw_decision_ids,
                idempotency_key=(
                    f"user-notification/{normalized_channel.lower()}/{binding.id}/"
                    f"{snapshot_id}/{batch_key}"
                ),
                status="PENDING",
            )
            session.add(delivery)
            await session.flush()
            deliveries.append(delivery)
        return deliveries

    async def batch_delivery_ids(
        self,
        *,
        channel: str,
        snapshot_id: UUID,
        decision_ids: list[UUID],
    ) -> list[UUID]:
        batch_key = decision_batch_key(decision_ids)
        async with self._session_factory() as session:
            return list(
                (
                    await session.scalars(
                        select(NotificationDeliveryRecord.id)
                        .where(
                            NotificationDeliveryRecord.channel == normalize_channel(channel),
                            NotificationDeliveryRecord.snapshot_id == snapshot_id,
                            NotificationDeliveryRecord.decision_batch_key == batch_key,
                            NotificationDeliveryRecord.status.in_(("PENDING", "FAILED", "SENDING")),
                        )
                        .order_by(NotificationDeliveryRecord.created_at)
                    )
                ).all()
            )

    async def start_delivery(self, delivery_id: UUID) -> DeliveryTarget | None:
        now = datetime.now(UTC)
        async with self._session_factory() as session, session.begin():
            delivery = await session.get(NotificationDeliveryRecord, delivery_id)
            if delivery is None:
                raise ValueError("notification delivery does not exist")
            if delivery.status in {"SENT", "EXPIRED", "CANCELLED"}:
                return None
            binding = await session.get(NotificationBindingRecord, delivery.binding_id)
            if binding is None or not await self._binding_is_allowed(session, binding, now=now):
                delivery.status = "CANCELLED"
                delivery.last_error = "binding, preference, or realtime entitlement is no longer active"
                return None
            delivery.status = "SENDING"
            delivery.attempt_count += 1
            delivery.last_attempt_at = now
            delivery.last_error = None
            return DeliveryTarget(
                delivery_id=delivery.id,
                user_id=delivery.user_id,
                binding_id=binding.id,
                channel=delivery.channel,
                destination=dict(binding.destination),
                label=binding.label,
                idempotency_key=delivery.idempotency_key,
                snapshot_id=delivery.snapshot_id,
                decision_ids=tuple(UUID(item) for item in delivery.decision_ids),
                decision_batch_key=delivery.decision_batch_key,
            )

    async def mark_sent(self, delivery_id: UUID, provider_message_id: str | None) -> None:
        async with self._session_factory() as session, session.begin():
            delivery = await session.get(NotificationDeliveryRecord, delivery_id)
            if delivery is None:
                raise ValueError("notification delivery does not exist")
            delivery.status = "SENT"
            delivery.sent_at = datetime.now(UTC)
            delivery.provider_message_id = provider_message_id
            delivery.last_error = None

    async def mark_failed(self, delivery_id: UUID, exc: Exception) -> None:
        async with self._session_factory() as session, session.begin():
            delivery = await session.get(NotificationDeliveryRecord, delivery_id)
            if delivery is not None:
                delivery.status = "FAILED"
                delivery.last_error = f"{type(exc).__name__}: {exc}"

    async def mark_expired(self, delivery_id: UUID, reason: str) -> None:
        async with self._session_factory() as session, session.begin():
            delivery = await session.get(NotificationDeliveryRecord, delivery_id)
            if delivery is not None:
                delivery.status = "EXPIRED"
                delivery.last_error = reason

    async def delivery_receipt(self, delivery_id: UUID) -> tuple[NotificationDeliveryRecord, dict]:
        async with self._session_factory() as session:
            delivery = await session.get(NotificationDeliveryRecord, delivery_id)
            if delivery is None:
                raise ValueError("notification delivery does not exist")
            binding = await session.get(NotificationBindingRecord, delivery.binding_id)
            return delivery, dict(binding.destination) if binding is not None else {}

    async def _binding_is_allowed(
        self,
        session: AsyncSession,
        binding: NotificationBindingRecord,
        *,
        now: datetime,
    ) -> bool:
        if binding.status != "ACTIVE" or binding.verified_at is None:
            return False
        entitlement = await session.scalar(
            select(UserEntitlementRecord.id)
            .where(
                UserEntitlementRecord.user_id == binding.user_id,
                UserEntitlementRecord.entitlement == REALTIME_NOTIFICATIONS_ENTITLEMENT,
                UserEntitlementRecord.status == "ACTIVE",
                or_(
                    UserEntitlementRecord.starts_at.is_(None),
                    UserEntitlementRecord.starts_at <= now,
                ),
                or_(
                    UserEntitlementRecord.expires_at.is_(None),
                    UserEntitlementRecord.expires_at > now,
                ),
            )
            .limit(1)
        )
        if entitlement is None:
            return False
        preference = await session.scalar(
            select(NotificationPreferenceRecord.enabled)
            .where(
                NotificationPreferenceRecord.user_id == binding.user_id,
                NotificationPreferenceRecord.event_type == EVENT_AI_DECISION,
                NotificationPreferenceRecord.channel == binding.channel,
            )
            .limit(1)
        )
        return preference is not False

    async def _upsert_verified_binding(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        channel: str,
        destination_key: str,
        destination: dict[str, Any],
        label: str | None,
        verified_at: datetime,
    ) -> NotificationBindingRecord:
        existing = await session.scalar(
            select(NotificationBindingRecord)
            .where(
                NotificationBindingRecord.channel == channel,
                NotificationBindingRecord.destination_key == destination_key,
            )
            .limit(1)
            .with_for_update()
        )
        now = datetime.now(UTC)
        if existing is not None:
            if existing.user_id != user_id:
                raise NotificationBindingConflict("notification destination is already bound")
            existing.destination = destination
            existing.label = label or existing.label
            existing.status = "ACTIVE"
            existing.verified_at = verified_at
            existing.updated_at = now
            return existing
        binding = NotificationBindingRecord(
            user_id=user_id,
            channel=channel,
            destination_key=destination_key,
            destination=destination,
            label=label,
            status="ACTIVE",
            verified_at=verified_at,
            created_at=now,
            updated_at=now,
        )
        session.add(binding)
        await session.flush()
        return binding

    async def _ensure_preference(
        self,
        session: AsyncSession,
        user_id: UUID,
        channel: str,
        *,
        enabled: bool,
        overwrite: bool = False,
    ) -> NotificationPreferenceRecord:
        preference = await session.scalar(
            select(NotificationPreferenceRecord)
            .where(
                NotificationPreferenceRecord.user_id == user_id,
                NotificationPreferenceRecord.event_type == EVENT_AI_DECISION,
                NotificationPreferenceRecord.channel == channel,
            )
            .limit(1)
            .with_for_update()
        )
        now = datetime.now(UTC)
        if preference is None:
            preference = NotificationPreferenceRecord(
                user_id=user_id,
                event_type=EVENT_AI_DECISION,
                channel=channel,
                enabled=enabled,
                created_at=now,
                updated_at=now,
            )
            session.add(preference)
            return preference
        if overwrite:
            preference.enabled = enabled
            preference.updated_at = now
        return preference

    @staticmethod
    def binding_payload(binding: NotificationBindingRecord) -> dict:
        return {
            "id": str(binding.id),
            "channel": binding.channel,
            "label": binding.label,
            "status": binding.status,
            "verified_at": binding.verified_at,
            "destination": _safe_destination(binding.channel, binding.destination),
            "created_at": binding.created_at,
        }

    @staticmethod
    def delivery_payload(delivery: NotificationDeliveryRecord) -> dict:
        return {
            "id": str(delivery.id),
            "channel": delivery.channel,
            "event_type": delivery.event_type,
            "status": delivery.status,
            "attempt_count": delivery.attempt_count,
            "sent_at": delivery.sent_at,
            "last_error": delivery.last_error,
            "created_at": delivery.created_at,
        }


def normalize_channel(channel: str) -> str:
    value = channel.strip().upper()
    if value not in NOTIFICATION_CHANNELS:
        raise ValueError(f"unsupported notification channel: {channel}")
    return value


def decision_batch_key(decision_ids: list[UUID]) -> str:
    material = ",".join(sorted(str(item) for item in decision_ids))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def qq_destination_key(scope: str, target_id: str) -> str:
    return f"{scope.strip().lower()}:{target_id.strip()}"


def wechat_destination_key(account_id: str, user_id: str) -> str:
    return f"{account_id.strip()}:{user_id.strip()}"


def _pairing_digest(code: str) -> str:
    normalized = _PAIRING_CODE_RE.sub("", code.strip().upper())
    if len(normalized) < 6:
        raise NotificationPairingError("pairing code is invalid or expired")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _format_pairing_code(value: str) -> str:
    return f"{value[:4]}-{value[4:8]}"


def _safe_destination(channel: str, destination: dict) -> dict:
    if channel == CHANNEL_EMAIL:
        return {"email": destination.get("email")}
    if channel == CHANNEL_QQ:
        return {
            "scope": destination.get("scope"),
            "target_id": _mask_identifier(destination.get("target_id")),
        }
    if channel == CHANNEL_WECHAT:
        return {
            "account_id": destination.get("account_id"),
            "user_id": _mask_identifier(destination.get("user_id")),
        }
    return {}


def _mask_identifier(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    if len(value) <= 8:
        return value[:2] + "***"
    return f"{value[:4]}…{value[-4:]}"


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
