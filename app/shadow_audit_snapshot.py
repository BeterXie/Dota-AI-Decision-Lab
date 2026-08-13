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
