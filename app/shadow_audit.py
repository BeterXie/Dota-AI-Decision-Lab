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
    side = _side_identity(snapshots)
    return {
        "schema_version": "shadow-run-audit-v1",
        "generated_at": generated_at.isoformat(),
        "map": {
            "canonical_map_id": str(canonical_map.id),
            "canonical_series_id": str(canonical_map.series_id) if canonical_map.series_id else None,
            "map_number": canonical_map.map_number,
            "valve_match_id": canonical_map.valve_match_id,
        },
        "side_identity": side,
        "snapshots": {
            "count": len(snapshots),
            "mode_counts": dict(modes),
        },
    }


def _side_identity(snapshots: list[DecisionSnapshotRecord]) -> dict[str, Any]:
    statuses: Counter[str] = Counter()
    pairs: set[tuple[str, str]] = set()
    latest = None
    for snapshot in snapshots:
        identity = snapshot.canonical_payload.get("identity", {})
        raw = identity.get("side_identity") if isinstance(identity, dict) else None
        if not isinstance(raw, dict):
            continue
        status = str(raw.get("status") or "UNKNOWN")
        statuses[status] += 1
        radiant = raw.get("radiant_team_id")
        dire = raw.get("dire_team_id")
        if status == "RESOLVED" and isinstance(radiant, str) and isinstance(dire, str):
            pairs.add((radiant, dire))
        latest = raw
    return {
        "status_counts": dict(statuses),
        "resolved_pair_count": len(pairs),
        "stable": len(pairs) <= 1 and statuses.get("CONFLICT", 0) == 0,
        "latest": latest,
    }
