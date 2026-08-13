from collections import Counter
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DecisionSnapshotRecord, LiveSyncEstimateRecord


def snapshot_quality(snapshots: list[DecisionSnapshotRecord]) -> dict[str, Any]:
    warnings: Counter[str] = Counter()
    blockers: Counter[str] = Counter()
    for snapshot in snapshots:
        quality = snapshot.canonical_payload.get("quality", {})
        if not isinstance(quality, dict):
            continue
        warnings.update(str(item) for item in quality.get("warnings", []) if item)
        blockers.update(str(item) for item in quality.get("blockers", []) if item)
    return {
        "count": len(snapshots),
        "mode_counts": dict(Counter(snapshot.mode for snapshot in snapshots)),
        "live_snapshot_count": sum(snapshot.mode.startswith("LIVE_") for snapshot in snapshots),
        "warning_counts": dict(warnings),
        "blocker_counts": dict(blockers),
    }


def live_freshness(snapshots: list[DecisionSnapshotRecord]) -> dict[str, Any]:
    evidence: list[tuple[DecisionSnapshotRecord, dict[str, Any]]] = []
    for snapshot in snapshots:
        quality = snapshot.canonical_payload.get("quality", {})
        raw = quality.get("live_field_freshness") if isinstance(quality, dict) else None
        if isinstance(raw, dict):
            evidence.append((snapshot, raw))
    return {
        "snapshot_count_with_field_evidence": len(evidence),
        "complete_snapshot_count": sum(raw.get("complete") is True for _, raw in evidence),
        "incomplete_snapshot_count": sum(raw.get("complete") is False for _, raw in evidence),
        "latest": (
            {
                "snapshot_id": str(evidence[-1][0].id),
                "decision_at": evidence[-1][0].decision_at.isoformat(),
                **evidence[-1][1],
            }
            if evidence
            else None
        ),
    }


async def temporal_alignment(session: AsyncSession, canonical_map_id: UUID) -> dict[str, Any]:
    estimates = list(
        (
            await session.scalars(
                select(LiveSyncEstimateRecord)
                .where(LiveSyncEstimateRecord.canonical_map_id == canonical_map_id)
                .order_by(LiveSyncEstimateRecord.calculated_at)
            )
        ).all()
    )
    latest = estimates[-1] if estimates else None
    return {
        "estimate_count": len(estimates),
        "status_counts": dict(Counter(item.status for item in estimates)),
        "confidence_counts": dict(Counter(item.confidence for item in estimates)),
        "latest": (
            {
                "status": latest.status,
                "confidence": latest.confidence,
                "estimated_lag_seconds": latest.estimated_lag_seconds,
                "p50_seconds": latest.p50_seconds,
                "p90_seconds": latest.p90_seconds,
                "jitter_seconds": latest.jitter_seconds,
                "sample_size": latest.sample_size,
                "accepted_pair_ratio": latest.accepted_pair_ratio,
                "ambiguous_ratio": latest.ambiguous_ratio,
                "outlier_ratio": latest.outlier_ratio,
            }
            if latest is not None
            else None
        ),
    }
