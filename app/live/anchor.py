"""Real game-start anchor for live decision timing.

Production evidence (2026-08-14 TI captures):

- DLTV payloads carry ``is_picks_ended_time`` (unix seconds): the real wall
  time the current map's ban/pick phase ended, i.e. the real game start.
- RayBet raw_status transitions are NOT a game-start anchor (they flip at
  listing/BP start, hours early for many matches).
- DLTV delivery is real-time (payload ``now`` equals receipt time); some
  broadcasts start the game clock at game start, others include the BP phase,
  so the broadcast clock alone cannot schedule "real game time" decisions.

The picks-ended timestamp is therefore the anchor for real in-game elapsed
time.  Unknown values stay unknown.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DltvLiveObservationRecord, ProviderRawEvent


async def picks_ended_anchor(
    session: AsyncSession,
    *,
    valve_match_id: int,
    decision_at: datetime,
) -> datetime | None:
    """Real game start: newest archived bootstrap carrying is_picks_ended_time."""
    event = await session.scalar(
        select(ProviderRawEvent)
        .where(
            ProviderRawEvent.provider == "dltv",
            ProviderRawEvent.event_type == "DLTV_BOOTSTRAP",
            ProviderRawEvent.provider_key == str(valve_match_id),
            ProviderRawEvent.received_at <= decision_at,
        )
        .order_by(ProviderRawEvent.received_at.desc())
        .limit(1)
    )
    if event is None:
        return None
    payload = event.payload
    if not isinstance(payload, dict):
        return None
    value = payload.get("is_picks_ended_time")
    if not isinstance(value, int) or isinstance(value, bool):
        return None
    return datetime.fromtimestamp(value, tz=UTC)


async def dltv_broadcast_start(
    session: AsyncSession,
    *,
    canonical_map_id: UUID,
    decision_at: datetime,
) -> datetime | None:
    """Earliest DLTV broadcast clock start (received_at - game_time_seconds).

    Only the earliest observations can anchor the broadcast start, so a small
    ordered sample is sufficient and avoids scanning the whole partition.
    """
    rows = list(
        (
            await session.execute(
                select(
                    DltvLiveObservationRecord.received_at,
                    DltvLiveObservationRecord.game_time_seconds,
                )
                .where(
                    DltvLiveObservationRecord.canonical_map_id == canonical_map_id,
                    DltvLiveObservationRecord.game_time_seconds.is_not(None),
                    DltvLiveObservationRecord.received_at <= decision_at,
                )
                .order_by(DltvLiveObservationRecord.received_at)
                .limit(100)
            )
        ).all()
    )
    candidates = [
        received_at - timedelta(seconds=game_time)
        for received_at, game_time in rows
        if game_time is not None
    ]
    return min(candidates) if candidates else None
