from app.snapshots import builder as _builder
from app.snapshots.builder import SnapshotBuildOutcome
from app.snapshots.gates import GateContext, evaluate_gate
from app.snapshots.repository import SnapshotRepository
from app.snapshots.side_aware import SideAwareSnapshotBuilder

SnapshotBuilder = SideAwareSnapshotBuilder
_builder.SnapshotBuilder = SideAwareSnapshotBuilder

__all__ = [
    "GateContext",
    "SnapshotBuildOutcome",
    "SnapshotBuilder",
    "SnapshotRepository",
    "evaluate_gate",
]
