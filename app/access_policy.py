from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AuthenticatedUser
from app.domain.competition import is_group_stage
from app.entitlements import (
    AI_DECISIONS_ENTITLEMENT,
    REALTIME_NOTIFICATIONS_ENTITLEMENT,
    EntitlementService,
)
from app.models import CanonicalMap, CanonicalSeries, MapResultRecord


@dataclass(frozen=True, slots=True)
class MapAccessDecision:
    canonical_map: CanonicalMap
    series: CanonicalSeries | None
    ai_allowed: bool
    ai_scope: str | None
    ai_public_projection: bool
    notification_allowed: bool
    notification_scope: str | None


async def resolve_map_access(
    session: AsyncSession,
    entitlements: EntitlementService,
    canonical_map_id: UUID,
    *,
    user: AuthenticatedUser | None,
) -> MapAccessDecision | None:
    """Resolve the product access contract for one canonical map.

    Group-stage AI Decisions are Free Access for everyone. Paid/unknown stages
    require an explicit entitlement while the map is active, then become public
    after a non-conflicting winner is confirmed. Realtime notifications always
    require an explicit scoped entitlement.

    Free Access intentionally receives the public AI projection only; it never
    exposes the frozen canonical snapshot payload or future-odds internals.
    An explicit entitlement always takes precedence over Free Access so stronger
    authorization never produces a weaker projection.
    """

    canonical_map = await session.get(CanonicalMap, canonical_map_id)
    if canonical_map is None:
        return None
    series = (
        await session.get(CanonicalSeries, canonical_map.series_id)
        if canonical_map.series_id is not None
        else None
    )
    result = await session.scalar(
        select(MapResultRecord).where(MapResultRecord.canonical_map_id == canonical_map.id)
    )

    ai_scope: str | None = None
    notification_scope: str | None = None
    if user is not None:
        ai_scope = await entitlements.access_scope(
            user.id,
            AI_DECISIONS_ENTITLEMENT,
            canonical_event_id=series.event_id if series is not None else None,
            canonical_series_id=canonical_map.series_id,
            canonical_map_id=canonical_map.id,
        )
        notification_scope = await entitlements.access_scope(
            user.id,
            REALTIME_NOTIFICATIONS_ENTITLEMENT,
            canonical_event_id=series.event_id if series is not None else None,
            canonical_series_id=canonical_map.series_id,
            canonical_map_id=canonical_map.id,
        )

    free_group_stage = series is not None and is_group_stage(series.stage_key)
    confirmed_result = (
        result is not None
        and result.winner_team_id is not None
        and not result.provider_conflict
    )
    public_scope = "FREE" if free_group_stage else "POSTMATCH" if confirmed_result else None
    public_projection = public_scope is not None and ai_scope is None
    if public_projection:
        ai_scope = public_scope

    return MapAccessDecision(
        canonical_map=canonical_map,
        series=series,
        ai_allowed=ai_scope is not None,
        ai_scope=ai_scope,
        ai_public_projection=public_projection,
        notification_allowed=notification_scope is not None,
        notification_scope=notification_scope,
    )
