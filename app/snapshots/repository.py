from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic_core import to_jsonable_python
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.canonical import content_digest
from app.domain.snapshot import DecisionSnapshot
from app.models import DecisionSnapshotRecord


class SnapshotRepository:
    async def get(self, session: AsyncSession, snapshot_id: UUID) -> DecisionSnapshot | None:
        record = await session.get(DecisionSnapshotRecord, snapshot_id)
        return _to_domain(record) if record is not None else None

    async def persist(
        self,
        session: AsyncSession,
        *,
        canonical_map_id: UUID | None,
        decision_at: datetime,
        mode: str,
        identity: dict[str, Any],
        market: dict[str, Any],
        draft: dict[str, Any] | None,
        history: dict[str, Any],
        live: dict[str, Any] | None,
        quality: dict[str, Any],
    ) -> DecisionSnapshot:
        canonical_payload = to_jsonable_python(
            {
                "schema_version": "decision-snapshot-v1",
                "decision_at": decision_at,
                "mode": mode,
                "identity": identity,
                "market": market,
                "draft": draft,
                "history": history,
                "live": live,
                "quality": quality,
            }
        )
        snapshot_hash = content_digest(canonical_payload)
        existing = await session.scalar(
            select(DecisionSnapshotRecord).where(
                DecisionSnapshotRecord.snapshot_hash == snapshot_hash
            )
        )
        if existing is not None:
            return _to_domain(existing)

        created_at = datetime.now(UTC)
        record = DecisionSnapshotRecord(
            id=uuid4(),
            canonical_map_id=canonical_map_id,
            decision_at=decision_at,
            created_at=created_at,
            mode=mode,
            canonical_payload=canonical_payload,
            snapshot_hash=snapshot_hash,
        )
        try:
            async with session.begin_nested():
                session.add(record)
                await session.flush()
        except IntegrityError:
            existing = await session.scalar(
                select(DecisionSnapshotRecord).where(
                    DecisionSnapshotRecord.snapshot_hash == snapshot_hash
                )
            )
            if existing is None:
                raise
            return _to_domain(existing)
        return _to_domain(record)


def _to_domain(record: DecisionSnapshotRecord) -> DecisionSnapshot:
    payload = record.canonical_payload
    return DecisionSnapshot(
        snapshot_id=record.id,
        decision_at=record.decision_at,
        created_at=record.created_at,
        mode=record.mode,
        identity=payload["identity"],
        market=payload["market"],
        draft=payload.get("draft"),
        history=payload["history"],
        live=payload.get("live"),
        quality=payload["quality"],
        snapshot_hash=record.snapshot_hash,
    )
