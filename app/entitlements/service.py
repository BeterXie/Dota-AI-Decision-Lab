from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import and_, or_, select
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
ACCESS_SCOPE_GLOBAL = "GLOBAL"
ACCESS_SCOPE_SERIES = "SERIES"
ACCESS_SCOPE_MAP = "MAP"
ACCESS_SCOPES = frozenset({ACCESS_SCOPE_GLOBAL, ACCESS_SCOPE_SERIES, ACCESS_SCOPE_MAP})
_DEVELOPMENT_SOURCE = "development"


@dataclass(frozen=True, slots=True)
class AccessGrant:
    entitlement: str
    source: str
    scope_type: str
    scope_ref: UUID | None
    campaign_key: str | None
    starts_at: datetime | None
    expires_at: datetime | None

    def public_payload(self) -> dict:
        return {
            "entitlement": self.entitlement,
            "scope_type": self.scope_type,
            "scope_ref": str(self.scope_ref) if self.scope_ref is not None else None,
            "campaign_key": self.campaign_key,
            "starts_at": self.starts_at,
            "expires_at": self.expires_at,
        }


class EntitlementService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def active_entitlements(
        self,
        user_id: UUID,
        *,
        now: datetime | None = None,
    ) -> tuple[str, ...]:
        """Return GLOBAL entitlements only.

        Keeping this contract global prevents a SERIES pass from making legacy
        callers or the frontend session payload believe the account owns full
        site-wide Pro access.
        """

        current = now or datetime.now(UTC)
        async with self._session_factory() as session:
            values = list(
                (
                    await session.scalars(
                        select(UserEntitlementRecord.entitlement)
                        .where(
                            UserEntitlementRecord.user_id == user_id,
                            UserEntitlementRecord.scope_type == ACCESS_SCOPE_GLOBAL,
                            UserEntitlementRecord.scope_ref.is_(None),
                            *_active_window_predicates(current),
                        )
                        .distinct()
                    )
                ).all()
            )
        return tuple(sorted(values))

    async def active_grants(
        self,
        user_id: UUID,
        *,
        now: datetime | None = None,
    ) -> tuple[AccessGrant, ...]:
        current = now or datetime.now(UTC)
        async with self._session_factory() as session:
            rows = list(
                (
                    await session.scalars(
                        select(UserEntitlementRecord)
                        .where(
                            UserEntitlementRecord.user_id == user_id,
                            *_active_window_predicates(current),
                        )
                        .order_by(
                            UserEntitlementRecord.entitlement,
                            UserEntitlementRecord.scope_type,
                            UserEntitlementRecord.expires_at,
                        )
                    )
                ).all()
            )
        return tuple(_grant_payload(row) for row in rows)

    async def has_entitlement(
        self,
        user_id: UUID,
        entitlement: str,
        *,
        now: datetime | None = None,
    ) -> bool:
        """Return whether a GLOBAL entitlement is active."""

        return (
            await self.access_scope(
                user_id,
                entitlement,
                now=now,
            )
            == ACCESS_SCOPE_GLOBAL
        )

    async def has_any_entitlement(
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
                    *_active_window_predicates(current),
                )
                .limit(1)
            )
        return row is not None

    async def has_resource_entitlement(
        self,
        user_id: UUID,
        entitlement: str,
        *,
        canonical_series_id: UUID | None = None,
        canonical_map_id: UUID | None = None,
        now: datetime | None = None,
    ) -> bool:
        return (
            await self.access_scope(
                user_id,
                entitlement,
                canonical_series_id=canonical_series_id,
                canonical_map_id=canonical_map_id,
                now=now,
            )
            is not None
        )

    async def access_scope(
        self,
        user_id: UUID,
        entitlement: str,
        *,
        canonical_series_id: UUID | None = None,
        canonical_map_id: UUID | None = None,
        now: datetime | None = None,
    ) -> str | None:
        current = now or datetime.now(UTC)
        async with self._session_factory() as session:
            scopes = list(
                (
                    await session.scalars(
                        select(UserEntitlementRecord.scope_type).where(
                            UserEntitlementRecord.user_id == user_id,
                            UserEntitlementRecord.entitlement == entitlement,
                            *_active_window_predicates(current),
                            _resource_scope_predicate(
                                canonical_series_id=canonical_series_id,
                                canonical_map_id=canonical_map_id,
                            ),
                        )
                    )
                ).all()
            )
        for scope in (ACCESS_SCOPE_GLOBAL, ACCESS_SCOPE_SERIES, ACCESS_SCOPE_MAP):
            if scope in scopes:
                return scope
        return None

    async def eligible_user_ids_for_resource(
        self,
        session: AsyncSession,
        user_ids: set[UUID],
        entitlement: str,
        *,
        canonical_series_id: UUID | None = None,
        canonical_map_id: UUID | None = None,
        now: datetime | None = None,
    ) -> set[UUID]:
        if not user_ids:
            return set()
        current = now or datetime.now(UTC)
        values = await session.scalars(
            select(UserEntitlementRecord.user_id)
            .where(
                UserEntitlementRecord.user_id.in_(user_ids),
                UserEntitlementRecord.entitlement == entitlement,
                *_active_window_predicates(current),
                _resource_scope_predicate(
                    canonical_series_id=canonical_series_id,
                    canonical_map_id=canonical_map_id,
                ),
            )
            .distinct()
        )
        return set(values.all())

    async def grant(
        self,
        user_id: UUID,
        entitlement: str,
        *,
        source: str,
        starts_at: datetime | None = None,
        expires_at: datetime | None = None,
        scope_type: str = ACCESS_SCOPE_GLOBAL,
        scope_ref: UUID | None = None,
        campaign_key: str | None = None,
    ) -> None:
        normalized_scope, normalized_ref = normalize_access_scope(scope_type, scope_ref)
        if entitlement not in PREMIUM_ENTITLEMENTS:
            raise ValueError(f"unsupported entitlement: {entitlement}")
        normalized_source = source.strip()
        if not normalized_source:
            raise ValueError("entitlement source is required")
        if starts_at is not None and expires_at is not None and expires_at <= starts_at:
            raise ValueError("entitlement expiry must be after its start")
        normalized_campaign = campaign_key.strip() if campaign_key and campaign_key.strip() else None
        now = datetime.now(UTC)
        async with self._session_factory() as session, session.begin():
            row = await session.scalar(
                select(UserEntitlementRecord)
                .where(
                    UserEntitlementRecord.user_id == user_id,
                    UserEntitlementRecord.entitlement == entitlement,
                    UserEntitlementRecord.source == normalized_source,
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
                        source=normalized_source,
                        scope_type=normalized_scope,
                        scope_ref=normalized_ref,
                        campaign_key=normalized_campaign,
                        starts_at=starts_at,
                        expires_at=expires_at,
                        created_at=now,
                        updated_at=now,
                    )
                )
                return
            if row.scope_type != normalized_scope or row.scope_ref != normalized_ref:
                raise ValueError("an entitlement source cannot move between access scopes")
            row.status = "ACTIVE"
            row.campaign_key = normalized_campaign
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


def normalize_access_scope(scope_type: str, scope_ref: UUID | None) -> tuple[str, UUID | None]:
    normalized = scope_type.strip().upper()
    if normalized not in ACCESS_SCOPES:
        raise ValueError(f"unsupported access scope: {scope_type}")
    if normalized == ACCESS_SCOPE_GLOBAL:
        if scope_ref is not None:
            raise ValueError("GLOBAL access scope cannot have a resource id")
        return normalized, None
    if scope_ref is None:
        raise ValueError(f"{normalized} access scope requires a resource id")
    return normalized, scope_ref


def _active_window_predicates(current: datetime) -> tuple:
    return (
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


def _resource_scope_predicate(
    *,
    canonical_series_id: UUID | None,
    canonical_map_id: UUID | None,
):
    predicates = [
        and_(
            UserEntitlementRecord.scope_type == ACCESS_SCOPE_GLOBAL,
            UserEntitlementRecord.scope_ref.is_(None),
        )
    ]
    if canonical_series_id is not None:
        predicates.append(
            and_(
                UserEntitlementRecord.scope_type == ACCESS_SCOPE_SERIES,
                UserEntitlementRecord.scope_ref == canonical_series_id,
            )
        )
    if canonical_map_id is not None:
        predicates.append(
            and_(
                UserEntitlementRecord.scope_type == ACCESS_SCOPE_MAP,
                UserEntitlementRecord.scope_ref == canonical_map_id,
            )
        )
    return or_(*predicates)


def _grant_payload(row: UserEntitlementRecord) -> AccessGrant:
    return AccessGrant(
        entitlement=row.entitlement,
        source=row.source,
        scope_type=row.scope_type,
        scope_ref=row.scope_ref,
        campaign_key=row.campaign_key,
        starts_at=row.starts_at,
        expires_at=row.expires_at,
    )
