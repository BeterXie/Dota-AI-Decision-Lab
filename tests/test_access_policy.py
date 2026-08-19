from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.access_policy import resolve_map_access
from app.entitlements import AI_DECISIONS_ENTITLEMENT, REALTIME_NOTIFICATIONS_ENTITLEMENT
from app.models import CanonicalMap, CanonicalSeries


@pytest.mark.asyncio
async def test_group_stage_is_anonymous_free_access_with_public_projection() -> None:
    map_id = uuid4()
    series_id = uuid4()
    event_id = uuid4()
    canonical_map = SimpleNamespace(id=map_id, series_id=series_id)
    series = SimpleNamespace(id=series_id, event_id=event_id, stage_key="GROUP_STAGE")
    session = AsyncMock()

    async def get(model, record_id):
        if model is CanonicalMap and record_id == map_id:
            return canonical_map
        if model is CanonicalSeries and record_id == series_id:
            return series
        return None

    session.get.side_effect = get
    session.scalar.return_value = None
    entitlements = AsyncMock()

    access = await resolve_map_access(session, entitlements, map_id, user=None)

    assert access is not None
    assert access.ai_allowed is True
    assert access.ai_scope == "FREE"
    assert access.ai_public_projection is True
    assert access.notification_allowed is False
    entitlements.access_scope.assert_not_awaited()


@pytest.mark.asyncio
async def test_paid_stage_stays_locked_without_an_explicit_grant() -> None:
    map_id = uuid4()
    series_id = uuid4()
    event_id = uuid4()
    canonical_map = SimpleNamespace(id=map_id, series_id=series_id)
    series = SimpleNamespace(id=series_id, event_id=event_id, stage_key="PAID_STAGE")
    session = AsyncMock()

    async def get(model, record_id):
        if model is CanonicalMap and record_id == map_id:
            return canonical_map
        if model is CanonicalSeries and record_id == series_id:
            return series
        return None

    session.get.side_effect = get
    session.scalar.return_value = None
    entitlements = AsyncMock()

    access = await resolve_map_access(session, entitlements, map_id, user=None)

    assert access is not None
    assert access.ai_allowed is False
    assert access.ai_scope is None
    assert access.ai_public_projection is False
    assert access.notification_allowed is False


@pytest.mark.asyncio
async def test_paid_stage_grant_unlocks_full_ai_and_scoped_notifications() -> None:
    map_id = uuid4()
    series_id = uuid4()
    event_id = uuid4()
    user_id = uuid4()
    canonical_map = SimpleNamespace(id=map_id, series_id=series_id)
    series = SimpleNamespace(id=series_id, event_id=event_id, stage_key="PAID_STAGE")
    user = SimpleNamespace(id=user_id)
    session = AsyncMock()

    async def get(model, record_id):
        if model is CanonicalMap and record_id == map_id:
            return canonical_map
        if model is CanonicalSeries and record_id == series_id:
            return series
        return None

    session.get.side_effect = get
    session.scalar.return_value = None
    entitlements = AsyncMock()

    async def access_scope(_user_id, entitlement, **_kwargs):
        if entitlement in {AI_DECISIONS_ENTITLEMENT, REALTIME_NOTIFICATIONS_ENTITLEMENT}:
            return "SERIES"
        return None

    entitlements.access_scope.side_effect = access_scope

    access = await resolve_map_access(session, entitlements, map_id, user=user)

    assert access is not None
    assert access.ai_allowed is True
    assert access.ai_scope == "SERIES"
    assert access.ai_public_projection is False
    assert access.notification_allowed is True
    assert access.notification_scope == "SERIES"


@pytest.mark.asyncio
async def test_confirmed_result_opens_paid_stage_with_public_projection() -> None:
    map_id = uuid4()
    series_id = uuid4()
    canonical_map = SimpleNamespace(id=map_id, series_id=series_id)
    series = SimpleNamespace(id=series_id, event_id=uuid4(), stage_key="PAID_STAGE")
    session = AsyncMock()

    async def get(model, record_id):
        if model is CanonicalMap and record_id == map_id:
            return canonical_map
        if model is CanonicalSeries and record_id == series_id:
            return series
        return None

    session.get.side_effect = get
    session.scalar.return_value = SimpleNamespace(
        winner_team_id=uuid4(),
        provider_conflict=False,
    )
    entitlements = AsyncMock()

    access = await resolve_map_access(session, entitlements, map_id, user=None)

    assert access is not None
    assert access.ai_allowed is True
    assert access.ai_scope == "POSTMATCH"
    assert access.ai_public_projection is True
    assert access.notification_allowed is False
