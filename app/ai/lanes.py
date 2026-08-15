import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from itertools import count

from app.domain.snapshot import DecisionSnapshot
from app.time import ensure_utc


@dataclass
class _LaneState:
    condition: asyncio.Condition = field(default_factory=asyncio.Condition)
    active: bool = False
    waiters: list[tuple[datetime, int]] = field(default_factory=list)


class AiExperimentLaneRegistry:
    """Process-local ordering for one match/provider/model decision stream.

    The production runtime is a single supervised process with a concurrent AI
    worker pool.  Different providers and different matches remain concurrent,
    while checkpoints for the same provider/model lane enter PREPARE only after
    the preceding lane item has finished PERSIST.  That keeps prior_decisions
    and virtual bankroll deterministic even when several durable jobs are
    claimed at once.

    If the runtime is ever deployed as multiple replicas, this registry should
    be replaced by a database/distributed lane lease; the current localhost
    deployment intentionally has one runtime process.
    """

    def __init__(self) -> None:
        self._lanes: dict[str, _LaneState] = {}
        self._sequence = count()

    @asynccontextmanager
    async def hold(self, lane_key: str, decision_at: datetime) -> AsyncIterator[None]:
        lane = self._lanes.setdefault(lane_key, _LaneState())
        token = (ensure_utc(decision_at), next(self._sequence))
        async with lane.condition:
            lane.waiters.append(token)
            lane.condition.notify_all()

        # Give sibling worker tasks one event-loop turn to register.  The lane
        # then selects the earliest decision_at, rather than whichever task won
        # scheduler timing by a few microseconds.
        await asyncio.sleep(0)

        async with lane.condition:
            await lane.condition.wait_for(lambda: not lane.active and token == min(lane.waiters))
            lane.waiters.remove(token)
            lane.active = True
        try:
            yield
        finally:
            async with lane.condition:
                lane.active = False
                lane.condition.notify_all()
            if not lane.waiters and not lane.active:
                self._lanes.pop(lane_key, None)


def ai_experiment_lane_key(
    snapshot: DecisionSnapshot,
    *,
    provider: str,
    model: str,
) -> str:
    identity = snapshot.identity if isinstance(snapshot.identity, dict) else {}
    match_scope = (
        identity.get("map_id")
        or identity.get("canonical_map_id")
        or identity.get("valve_match_id")
        or identity.get("series_id")
        or snapshot.snapshot_id
    )
    return f"{match_scope}:{provider}:{model}"
