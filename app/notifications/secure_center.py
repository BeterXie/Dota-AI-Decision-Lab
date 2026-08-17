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
from app.notifications.center import PAIRABLE_CHANNELS, NotificationPairingError, normalize_channel
from app.notifications.center import (
    NotificationCenterService as BaseNotificationCenterService,
)
from app.notifications.models import (
    NotificationBindingRecord,
    NotificationPairingCodeRecord,
)

_PAIRING_CODE_TTL_SECONDS = 600
_PAIRING_CODE_BYTES = 12
_PAIRING_CODE_HEX_LENGTH = _PAIRING_CODE_BYTES * 2
_PAIRING_CODE_RE = re.compile(r"[^A-F0-9]")


class NotificationCenterService(BaseNotificationCenterService):
    """Production notification center with fail-closed account and pairing guards."""

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

    async def eligible_bindings(
        self,
        session: AsyncSession,
        channel: str,
        *,
        event_type: str = "AI_DECISION",
        now: datetime | None = None,
    ) -> list[NotificationBindingRecord]:
        bindings = await super().eligible_bindings(
            session,
            channel,
            event_type=event_type,
            now=now,
        )
        if not bindings:
            return []
        active_user_ids = set(
            (
                await session.scalars(
                    select(UserAccountRecord.id).where(
                        UserAccountRecord.id.in_({item.user_id for item in bindings}),
                        UserAccountRecord.disabled_at.is_(None),
                    )
                )
            ).all()
        )
        return [item for item in bindings if item.user_id in active_user_ids]

    async def _binding_is_allowed(
        self,
        session: AsyncSession,
        binding: NotificationBindingRecord,
        *,
        now: datetime,
    ) -> bool:
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
        return await super()._binding_is_allowed(session, binding, now=now)


def _pairing_digest(code: str) -> str:
    normalized = _PAIRING_CODE_RE.sub("", code.strip().upper())
    if len(normalized) != _PAIRING_CODE_HEX_LENGTH:
        raise NotificationPairingError("pairing code is invalid or expired")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
