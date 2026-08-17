from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.entitlements.models import UserEntitlementRecord

AI_DECISIONS_ENTITLEMENT = "ai_decisions"
REALTIME_NOTIFICATIONS_ENTITLEMENT = "realtime_notifications"
PREMIUM_ENTITLEMENTS = frozenset(
    {
        AI_DECISIONS_ENTITLEMENT,
        REALTIME_NOTIFICATIONS_ENTITLEMENT,
    }
)
_DEVELOPMENT_SOURCE = "development"


class EntitlementService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def active_entitlements(
        self,
        user_id: UUID,
        *,
        now: datetime | None = None,
    ) -> tuple[str, ...]:
        current = now or datetime.now(UTC)
        async with self._session_factory() as session:
            values = list(
                (
                    await session.scalars(
                        select(UserEntitlementRecord.entitlement)
                        .where(
                            UserEntitlementRecord.user_id == user_id,
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
        return tuple(sorted(values))

    async def has_entitlement(
        self,
        user_id: UUID,
        entitlement: str,
        *,
        now: datetime | None = None,
    ) -> bool:
        current = now or datetime.now(UTC)
        async with self._session_factory() as session:
            row = await session.scalar(
                select(UserEntitlementRecord.id)
                .where(
                    UserEntitlementRecord.user_id == user_id,
                    UserEntitlementRecord.entitlement == entitlement,
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
                .limit(1)
            )
        return row is not None

    async def grant(
        self,
        user_id: UUID,
        entitlement: str,
        *,
        source: str,
        starts_at: datetime | None = None,
        expires_at: datetime | None = None,
    ) -> None:
        if entitlement not in PREMIUM_ENTITLEMENTS:
            raise ValueError(f"unsupported entitlement: {entitlement}")
        if not source.strip():
            raise ValueError("entitlement source is required")
        now = datetime.now(UTC)
        async with self._session_factory() as session, session.begin():
            row = await session.scalar(
                select(UserEntitlementRecord)
                .where(
                    UserEntitlementRecord.user_id == user_id,
                    UserEntitlementRecord.entitlement == entitlement,
                    UserEntitlementRecord.source == source,
                )
                .limit(1)
                .with_for_update()
            )
            if row is None:
                session.add(
                    UserEntitlementRecord(
                        user_id=user_id,
                        entitlement=entitlement,
                        status="ACTIVE",
                        source=source,
                        starts_at=starts_at,
                        expires_at=expires_at,
                        created_at=now,
                        updated_at=now,
                    )
                )
                return
            row.status = "ACTIVE"
            row.starts_at = starts_at
            row.expires_at = expires_at
            row.updated_at = now

    async def revoke(self, user_id: UUID, entitlement: str, *, source: str) -> None:
        async with self._session_factory() as session, session.begin():
            row = await session.scalar(
                select(UserEntitlementRecord)
                .where(
                    UserEntitlementRecord.user_id == user_id,
                    UserEntitlementRecord.entitlement == entitlement,
                    UserEntitlementRecord.source == source,
                )
                .limit(1)
                .with_for_update()
            )
            if row is not None:
                row.status = "REVOKED"
                row.updated_at = datetime.now(UTC)

    async def ensure_development_grants(
        self,
        user_id: UUID,
        email: str,
        allowed_emails: tuple[str, ...],
    ) -> tuple[str, ...]:
        normalized_allowlist = {value.strip().lower() for value in allowed_emails if value.strip()}
        if email.lower() not in normalized_allowlist:
            return await self.active_entitlements(user_id)
        for entitlement in PREMIUM_ENTITLEMENTS:
            await self.grant(
                user_id,
                entitlement,
                source=_DEVELOPMENT_SOURCE,
            )
        return await self.active_entitlements(user_id)
