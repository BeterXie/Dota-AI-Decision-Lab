from collections import Counter
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AiDecisionRecord, DecisionSnapshotRecord


async def ai_report(
    session: AsyncSession, snapshots: list[DecisionSnapshotRecord]
) -> dict[str, Any]:
    ids = [snapshot.id for snapshot in snapshots]
    decisions = (
        list(
            (
                await session.scalars(
                    select(AiDecisionRecord).where(AiDecisionRecord.snapshot_id.in_(ids))
                )
            ).all()
        )
        if ids
        else []
    )
    hashes = {snapshot.id: snapshot.snapshot_hash for snapshot in snapshots}
    return {
        "decision_count": len(decisions),
        "provider_counts": dict(Counter(item.provider for item in decisions)),
        "parse_status_counts": dict(Counter(item.parse_status for item in decisions)),
        "snapshot_hash_mismatch_count": sum(
            hashes.get(item.snapshot_id) != item.snapshot_hash for item in decisions
        ),
    }
