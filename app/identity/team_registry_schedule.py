from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.jobs import JobType
from app.jobs.repository import JobRepository
from app.models import CanonicalEvent, CanonicalSeries, ProviderEventMapping


@dataclass(frozen=True, slots=True)
class TeamRegistryScheduleResult:
    events_considered: int
    jobs_enqueued: int


@dataclass(frozen=True, slots=True)
class _EventTeams:
    event_id: UUID
    created_at: datetime
    started_at: datetime | None
    team_ids: tuple[UUID, ...]


async def schedule_discovered_event_team_registry_refreshes(
    session: AsyncSession,
    jobs: JobRepository,
    *,
    discovered_after: datetime,
    now: datetime | None = None,
) -> TeamRegistryScheduleResult:
    """Enqueue one registry refresh when a RayBet event is first discovered."""

    observed_at = now or datetime.now(UTC)
    events = await _raybet_event_teams(session, created_after=discovered_after)
    enqueued = 0
    for event in events:
        if not event.team_ids:
            continue
        await _enqueue_event_refresh(
            session,
            jobs,
            event=event,
            cycle="discovered",
            observed_at=observed_at,
        )
        enqueued += 1
    return TeamRegistryScheduleResult(len(events), enqueued)


async def schedule_prestart_event_team_registry_refreshes(
    session: AsyncSession,
    jobs: JobRepository,
    *,
    refresh_seconds: float = 86_400.0,
    now: datetime | None = None,
) -> TeamRegistryScheduleResult:
    """Refresh event teams once per 24h cycle until the event begins.

    The periodic scheduler may run more frequently than the provider refresh. A
    cycle-specific durable-job dedupe key guarantees the OpenDota registry work
    runs at most once per configured interval for each event/team-set snapshot.
    """

    if refresh_seconds <= 0:
        raise ValueError("refresh_seconds must be positive")
    observed_at = now or datetime.now(UTC)
    events = await _raybet_event_teams(session)
    enqueued = 0
    for event in events:
        if event.started_at is None or event.started_at <= observed_at:
            continue
        elapsed = max(0.0, (observed_at - event.created_at).total_seconds())
        cycle_number = int(elapsed // refresh_seconds)
        # Cycle zero is the discovery refresh. Recurring work starts only after
        # one complete interval so discovery cannot cause a duplicate refresh.
        if cycle_number < 1 or not event.team_ids:
            continue
        await _enqueue_event_refresh(
            session,
            jobs,
            event=event,
            cycle=f"prestart-{cycle_number}",
            observed_at=observed_at,
        )
        enqueued += 1
    return TeamRegistryScheduleResult(len(events), enqueued)


async def _raybet_event_teams(
    session: AsyncSession,
    *,
    created_after: datetime | None = None,
) -> list[_EventTeams]:
    statement = (
        select(
            CanonicalEvent.id,
            CanonicalEvent.created_at,
            CanonicalEvent.started_at,
            CanonicalSeries.team_a_id,
            CanonicalSeries.team_b_id,
            CanonicalSeries.scheduled_at,
        )
        .join(CanonicalSeries, CanonicalSeries.event_id == CanonicalEvent.id)
        .where(
            select(ProviderEventMapping.id)
            .where(
                ProviderEventMapping.provider == "raybet",
                ProviderEventMapping.canonical_event_id == CanonicalEvent.id,
            )
            .exists()
        )
        .order_by(CanonicalEvent.created_at, CanonicalEvent.id)
    )
    if created_after is not None:
        statement = statement.where(CanonicalEvent.created_at >= created_after)

    rows = (await session.execute(statement)).all()
    grouped: dict[UUID, dict[str, object]] = {}
    for event_id, created_at, explicit_started_at, team_a_id, team_b_id, scheduled_at in rows:
        state = grouped.setdefault(
            event_id,
            {
                "created_at": created_at,
                "explicit_started_at": explicit_started_at,
                "scheduled": [],
                "team_ids": set(),
            },
        )
        team_ids = state["team_ids"]
        scheduled = state["scheduled"]
        assert isinstance(team_ids, set)
        assert isinstance(scheduled, list)
        team_ids.update((team_a_id, team_b_id))
        if scheduled_at is not None:
            scheduled.append(scheduled_at)

    result: list[_EventTeams] = []
    for event_id, state in grouped.items():
        scheduled = state["scheduled"]
        explicit_started_at = state["explicit_started_at"]
        team_ids = state["team_ids"]
        assert isinstance(scheduled, list)
        assert isinstance(team_ids, set)
        inferred_started_at = min(scheduled) if scheduled else None
        started_at = explicit_started_at or inferred_started_at
        result.append(
            _EventTeams(
                event_id=event_id,
                created_at=state["created_at"],
                started_at=started_at,
                team_ids=tuple(sorted(team_ids, key=str)),
            )
        )
    return result


async def _enqueue_event_refresh(
    session: AsyncSession,
    jobs: JobRepository,
    *,
    event: _EventTeams,
    cycle: str,
    observed_at: datetime,
) -> None:
    team_values = [str(team_id) for team_id in event.team_ids]
    fingerprint = hashlib.sha256("|".join(team_values).encode("utf-8")).hexdigest()[:12]
    await jobs.enqueue(
        session,
        job_type=JobType.SYNC_TEAM_REGISTRY,
        dedupe_key=f"team-registry:{event.event_id}:{cycle}:{fingerprint}",
        payload={
            "canonical_event_id": str(event.event_id),
            "canonical_team_ids": team_values,
            "refresh_cycle": cycle,
            "scheduled_at": observed_at.isoformat(),
        },
        priority=120,
    )
