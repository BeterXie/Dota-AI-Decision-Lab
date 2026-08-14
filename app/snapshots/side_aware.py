"""Back-compat alias: the side-aware builder is now the production builder.

The implementation lives in `app.snapshots.builder.SnapshotBuilder`; this
module keeps the historical name and the private helpers that older tests
import, so there is no hidden monkey-patch wiring anywhere.
"""

from app.snapshots.builder import (  # noqa: F401
    SnapshotBuilder as SideAwareSnapshotBuilder,
)
from app.snapshots.builder import (
    _align_history_to_series,
    _live_window,
    _remove_unassigned_roster_history,
    _series_score,
)

__all__ = [
    "SideAwareSnapshotBuilder",
    "_align_history_to_series",
    "_live_window",
    "_remove_unassigned_roster_history",
    "_series_score",
]
