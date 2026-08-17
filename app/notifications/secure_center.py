from __future__ import annotations

import hashlib
import re
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import UserAccountRecord
from app.entitlements import REALTIME_NOTIFICATIONS_ENTITLEMENT, EntitlementService
from app.models import CanonicalMap, DecisionSnapshotRecord
from app.notifications.center import (
    EVENT_AI_DECISION,
    PAIRABLE_CHANNELS,
    DeliveryTarget,
    NotificationPairingError,
    decision_batch_key,
    normalize_channel,
)
from app.notifications.center import (
    NotificationCenterService as BaseNotificationCenterService,
)
from app.notifications.models import (
    NotificationBindingRecord,
    NotificationDeliveryRecord,
    NotificationPairingCodeRecord,
    NotificationPreferenceRecord,
)

_PAIRING_CODE_TTL_SECONDS = 600
_PAIRING_CODE_BYTES = 12
_PAIRING_CODE_HEX_LENGTH = _PAIRING_CODE_BYTES * 2
_PAIRING_CODE_RE = re.compile(r"[^A-F0-9]")


class NotificationCenterService(BaseNotificationCenterService):
    """Production notification center with fail-closed account, scope and pairing guards."""

    def __init__(self, session_factory) -> None:
        super().__init__(session_factory)
        self._entitlements = EntitlementService(session_factory)

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
        raw = secrets.token_hex(_PAIRING_CODE_BYTES).upper()
        code = "-".join(raw[index : index + 4] for index in range(0, len(raw), 4))
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
        normalized = _PAIRING_CODE_RE.sub("", code.strip().upper())
        if len(normalized) != _PAIRING_CODE_HEX_LENGTH:
            raise NotificationPairingError("pairing code is invalid or expired")
        return await super().consume_pairing_code(
            channel=channel,
            code=code,
            destination_key=destination_key,
            destination=destination,
            label=label,
        )

    async def bound_active_user_id(
        self,
        *,
        channel: str,
        destination_key: str,
    ) -> UUID | None:
        normalized_channel = normalize_channel(channel)
        async with self._session_factory() as session:
            return await session.scalar(
                select(NotificationBindingRecord.user_id)
                .join(
                    UserAccountRecord,
                    UserAccountRecord.id == NotificationBindingRecord.user_id,
                )
                .where(
                    NotificationBindingRecord.channel == normalized_channel,
                    NotificationBindingRecord.destination_key == destination_key,
                    NotificationBindingRecord.status == "ACTIVE",
                    NotificationBindingRecord.verified_at.is_not(None),
                    UserAccountRecord.disabled_at.is_(None),
                )
                .limit(1)
            )

    async def eligible_bindings(
        self,
        session: AsyncSession,
        channel: str,
        *,
        event_type: str = EVENT_AI_DECISION,
        now: datetime | None = None,
        canonical_series_id: UUID | None = None,
        canonical_map_id: UUID | None = None,
    ) -> list[NotificationBindingRecord]:
        normalized_channel = normalize_channel(channel)
        current = now or datetime.now(UTC)
        bindings = list(
            (
                await session.scalars(
                    select(NotificationBindingRecord)
                    .join(
                        UserAccountRecord,
                        UserAccountRecord.id == NotificationBindingRecord.user_id,
                    )
                    .where(
                        NotificationBindingRecord.channel == normalized_channel,
                        NotificationBindingRecord.status == "ACTIVE",
                        NotificationBindingRecord.verified_at.is_not(None),
                        UserAccountRecord.disabled_at.is_(None),
                    )
                )
            ).all()
        )
        if not bindings:
            return []
        entitled_users = await self._entitlements.eligible_user_ids_for_resource(
            session,
            {item.user_id for item in bindings},
            REALTIME_NOTIFICATIONS_ENTITLEMENT,
            canonical_series_id=canonical_series_id,
            canonical_map_id=canonical_map_id,
            now=current,
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
        canonical_series_id, canonical_map_id = await _snapshot_scope(session, snapshot_id)
        bindings = await self.eligible_bindings(
            session,
            normalized_channel,
            event_type=event_type,
            canonical_series_id=canonical_series_id,
            canonical_map_id=canonical_map_id,
        )
        batch_key = decision_batch_key(decision_ids)
        raw_decision_ids = [str(item) for item in sorted(decision_ids, key=str)]
        deliveries: list[NotificationDeliveryRecord] = []
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

    async def start_delivery(self, delivery_id: UUID) -> DeliveryTarget | None:
        now = datetime.now(UTC)
        async with self._session_factory() as session, session.begin():
            delivery = await session.get(NotificationDeliveryRecord, delivery_id)
            if delivery is None:
                raise ValueError("notification delivery does not exist")
            if delivery.status in {"SENT", "EXPIRED", "CANCELLED"}:
                return None
            binding = await session.get(NotificationBindingRecord, delivery.binding_id)
            canonical_series_id, canonical_map_id = await _snapshot_scope(
                session, delivery.snapshot_id
            )
            if binding is None or not await self._binding_is_allowed_for_resource(
                session,
                binding,
                event_type=delivery.event_type,
                now=now,
                canonical_series_id=canonical_series_id,
                canonical_map_id=canonical_map_id,
            ):
                delivery.status = "CANCELLED"
                delivery.last_error = "binding, preference, account, or scoped realtime entitlement is no longer active"
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

    async def _binding_is_allowed(
        self,
        session: AsyncSession,
        binding: NotificationBindingRecord,
        *,
        now: datetime,
    ) -> bool:
        return await self._binding_is_allowed_for_resource(
            session,
            binding,
            event_type=EVENT_AI_DECISION,
            now=now,
        )

    async def _binding_is_allowed_for_resource(
        self,
        session: AsyncSession,
        binding: NotificationBindingRecord,
        *,
        event_type: str,
        now: datetime,
        canonical_series_id: UUID | None = None,
        canonical_map_id: UUID | None = None,
    ) -> bool:
        if binding.status != "ACTIVE" or binding.verified_at is None:
            return False
        active_user = await session.scalar(
            select(UserAccountRecord.id)
            .where(
                UserAccountRecord.id == binding.user_id,
                UserAccountRecord.disabled_at.is_(None),
            )
            .limit(1)
        )
        if active_user is None:
            return False
        entitled = await self._entitlements.eligible_user_ids_for_resource(
            session,
            {binding.user_id},
            REALTIME_NOTIFICATIONS_ENTITLEMENT,
            canonical_series_id=canonical_series_id,
            canonical_map_id=canonical_map_id,
            now=now,
        )
        if binding.user_id not in entitled:
            return False
        preference = await session.scalar(
            select(NotificationPreferenceRecord.enabled)
            .where(
                NotificationPreferenceRecord.user_id == binding.user_id,
                NotificationPreferenceRecord.event_type == event_type,
                NotificationPreferenceRecord.channel == binding.channel,
            )
            .limit(1)
        )
        return preference is not False


async def _snapshot_scope(
    session: AsyncSession,
    snapshot_id: UUID,
) -> tuple[UUID | None, UUID | None]:
    snapshot = await session.get(DecisionSnapshotRecord, snapshot_id)
    if snapshot is None or snapshot.canonical_map_id is None:
        return None, None
    canonical_map = await session.get(CanonicalMap, snapshot.canonical_map_id)
    if canonical_map is None:
        return None, snapshot.canonical_map_id
    return canonical_map.series_id, canonical_map.id


def _pairing_digest(code: str) -> str:
    normalized = _PAIRING_CODE_RE.sub("", code.strip().upper())
    if len(normalized) != _PAIRING_CODE_HEX_LENGTH:
        raise NotificationPairingError("pairing code is invalid or expired")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
