from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AuthenticatedUser
from app.domain.competition import is_group_stage
from app.entitlements import (
    AI_DECISIONS_ENTITLEMENT,
    REALTIME_NOTIFICATIONS_ENTITLEMENT,
    EntitlementService,
)
from app.models import CanonicalMap, CanonicalSeries


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
    remain scoped to an explicit entitlement even after the map settles.
    Realtime notifications always require an explicit scoped entitlement.

    Free Access intentionally receives the public AI projection only; it never
    exposes the frozen canonical snapshot payload or future-odds internals.
    """

    canonical_map = await session.get(CanonicalMap, canonical_map_id)
    if canonical_map is None:
        return None
    series = (
        await session.get(CanonicalSeries, canonical_map.series_id)
        if canonical_map.series_id is not None
        else None
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
    if free_group_stage:
        ai_scope = "FREE"

    return MapAccessDecision(
        canonical_map=canonical_map,
        series=series,
        ai_allowed=free_group_stage or ai_scope is not None,
        ai_scope=ai_scope,
        ai_public_projection=free_group_stage,
        notification_allowed=notification_scope is not None,
        notification_scope=notification_scope,
    )
