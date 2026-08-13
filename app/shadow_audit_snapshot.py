from collections import Counter
from typing import Any

from app.models import DecisionSnapshotRecord


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
