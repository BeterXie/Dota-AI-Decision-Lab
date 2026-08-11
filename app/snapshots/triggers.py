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
) -> int:
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
                },
                occurred_at=observed_at,
            ),
        )
    return len(crossed)
