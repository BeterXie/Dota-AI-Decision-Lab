from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.events import DomainEvent
from app.models import DomainEventRecord, OutboxEventRecord


class EventRepository:
    async def record(
        self,
        session: AsyncSession,
        event: DomainEvent,
        *,
        topics: tuple[str, ...] = ("domain",),
    ) -> DomainEventRecord:
        dialect = session.get_bind().dialect.name
        if dialect == "postgresql":
            statement = (
                pg_insert(DomainEventRecord)
                .values(
                    event_type=event.event_type.value,
                    aggregate_type=event.aggregate_type,
                    aggregate_id=event.aggregate_id,
                    dedupe_key=event.dedupe_key,
                    payload=event.payload,
                    occurred_at=event.occurred_at,
                )
                .on_conflict_do_nothing(index_elements=["event_type", "dedupe_key"])
                .returning(DomainEventRecord.id)
            )
            event_id = await session.scalar(statement)
            if event_id is not None:
                record = await session.get(DomainEventRecord, event_id)
                assert record is not None
                for topic in topics:
                    session.add(
                        OutboxEventRecord(
                            domain_event_id=record.id,
                            topic=topic,
                            payload=event.payload,
                        )
                    )
                return record

        existing = await session.scalar(
            select(DomainEventRecord).where(
                DomainEventRecord.event_type == event.event_type.value,
                DomainEventRecord.dedupe_key == event.dedupe_key,
            )
        )
        if existing is not None:
            return existing
        record = DomainEventRecord(
            event_type=event.event_type.value,
            aggregate_type=event.aggregate_type,
            aggregate_id=event.aggregate_id,
            dedupe_key=event.dedupe_key,
            payload=event.payload,
            occurred_at=event.occurred_at,
        )
        session.add(record)
        await session.flush()
        for topic in topics:
            session.add(
                OutboxEventRecord(
                    domain_event_id=record.id,
                    topic=topic,
                    payload=event.payload,
                )
            )
        return record
