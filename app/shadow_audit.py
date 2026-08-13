from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CanonicalMap, DecisionSnapshotRecord


async def build_shadow_run_audit(
    session: AsyncSession,
    *,
    canonical_map_id: UUID,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    generated_at = generated_at or datetime.now(UTC)
    canonical_map = await session.get(CanonicalMap, canonical_map_id)
    if canonical_map is None:
        raise ValueError("canonical map does not exist")
    snapshots = list(
        (
            await session.scalars(
                select(DecisionSnapshotRecord)
                .where(DecisionSnapshotRecord.canonical_map_id == canonical_map_id)
                .order_by(DecisionSnapshotRecord.decision_at)
            )
        ).all()
    )
    modes = Counter(snapshot.mode for snapshot in snapshots)
    return {
        "schema_version": "shadow-run-audit-v1",
        "generated_at": generated_at.isoformat(),
        "map": {
            "canonical_map_id": str(canonical_map.id),
            "canonical_series_id": str(canonical_map.series_id) if canonical_map.series_id else None,
            "map_number": canonical_map.map_number,
            "valve_match_id": canonical_map.valve_match_id,
        },
        "snapshots": {
            "count": len(snapshots),
            "mode_counts": dict(modes),
        },
    }
