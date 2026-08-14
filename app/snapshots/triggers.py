from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.events import DomainEvent, DomainEventType
from app.events.outbox import EventRepository


async def record_crossed_checkpoints(
    session: AsyncSession,
    events: EventRepository,
    *,
    canonical_map_id: UUID,
    previous_game_time: int | None,
    current_game_time: int | None,
    checkpoint_minutes: tuple[int, ...],
    observed_at: datetime,
    real_elapsed_seconds: float | None = None,
    previous_real_elapsed_seconds: float | None = None,
) -> int:
    """Record decision checkpoints on real time when the anchor is known.

    When real_elapsed_seconds (time since the RayBet live anchor) is available,
    checkpoints fire on real elapsed minutes so decisions happen at real game
    minutes instead of the delayed broadcast clock.  Without an anchor the
    broadcast game clock is used as before.
    """
    if real_elapsed_seconds is not None:
        previous = (
            previous_real_elapsed_seconds if previous_real_elapsed_seconds is not None else -1
        )
        crossed = [
            minute
            for minute in checkpoint_minutes
            if previous < minute * 60 <= real_elapsed_seconds
        ]
        if previous_real_elapsed_seconds is None and crossed:
            crossed = [crossed[-1]]
        for minute in crossed:
            await events.record(
                session,
                DomainEvent(
                    event_type=DomainEventType.DECISION_CHECKPOINT_DUE,
                    aggregate_type="canonical_map",
                    aggregate_id=str(canonical_map_id),
                    dedupe_key=f"checkpoint-real:{canonical_map_id}:{minute}",
                    payload={
                        "canonical_map_id": str(canonical_map_id),
                        "decision_at": observed_at.isoformat(),
                        "checkpoint_minute": minute,
                        "basis": "real_time",
                    },
                    occurred_at=observed_at,
                ),
            )
        return len(crossed)
    if current_game_time is None:
        return 0
    crossed = [
        minute
        for minute in checkpoint_minutes
        if (previous_game_time or -1) < minute * 60 <= current_game_time
    ]
    if previous_game_time is None and crossed:
        crossed = [crossed[-1]]
    for minute in crossed:
        await events.record(
            session,
            DomainEvent(
                event_type=DomainEventType.DECISION_CHECKPOINT_DUE,
                aggregate_type="canonical_map",
                aggregate_id=str(canonical_map_id),
                dedupe_key=f"checkpoint:{canonical_map_id}:{minute}",
                payload={
                    "canonical_map_id": str(canonical_map_id),
                    "decision_at": observed_at.isoformat(),
                    "checkpoint_minute": minute,
                    "basis": "game_time",
                },
                occurred_at=observed_at,
            ),
        )
    return len(crossed)
