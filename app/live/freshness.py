from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ProviderRawEvent
from app.providers.dltv.parser import parse_fast_patch
from app.time import elapsed_seconds

LIVE_BASIC_REQUIRED_FIELDS = (
    "game_time_seconds",
    "radiant_kills",
    "dire_kills",
    "radiant_nw_lead",
)


@dataclass(frozen=True)
class LiveFieldFreshness:
    observed_at: dict[str, datetime]
    ages_seconds: dict[str, float]
    effective_age_seconds: float | None
    complete: bool

    def payload(self) -> dict[str, object]:
        return {
            "required_fields": list(LIVE_BASIC_REQUIRED_FIELDS),
            "observed_at": self.observed_at,
            "ages_seconds": self.ages_seconds,
            "effective_age_seconds": self.effective_age_seconds,
            "complete": self.complete,
        }


async def load_live_basic_field_freshness(
    session: AsyncSession,
    *,
    valve_match_id: int,
    decision_at: datetime,
    max_age_seconds: float,
) -> LiveFieldFreshness:
    """Resolve LIVE_BASIC freshness from append-only DLTV raw evidence.

    A newer sparse packet only refreshes the fields it actually carries. Exact
    normalized duplicates are ignored so repeated messages cannot make stale
    state appear fresh.
    """

    cutoff = decision_at - timedelta(seconds=max_age_seconds)
    records = list(
        (
            await session.scalars(
                select(ProviderRawEvent)
                .where(
                    ProviderRawEvent.provider == "dltv",
                    ProviderRawEvent.event_type == "DLTV_FAST_SOCKET",
                    ProviderRawEvent.provider_key == f"__nd2_match_{valve_match_id}",
                    ProviderRawEvent.received_at >= cutoff,
                    ProviderRawEvent.received_at <= decision_at,
                )
                .order_by(ProviderRawEvent.received_at.desc())
            )
        ).all()
    )

    observed_at: dict[str, datetime] = {}
    for record in records:
        if record.is_duplicate is True:
            continue
        patch = parse_fast_patch(
            record.payload,
            valve_match_id=valve_match_id,
            received_at=record.received_at,
            connection_id=record.connection_id,
            reconnect_generation=record.reconnect_generation or 0,
        )
        for field in LIVE_BASIC_REQUIRED_FIELDS:
            if field in observed_at:
                continue
            if field in patch.updates and patch.updates[field] is not None:
                observed_at[field] = record.received_at
        if len(observed_at) == len(LIVE_BASIC_REQUIRED_FIELDS):
            break

    ages_seconds = {
        field: elapsed_seconds(decision_at, observed_at[field])
        for field in LIVE_BASIC_REQUIRED_FIELDS
        if field in observed_at
    }
    complete = len(observed_at) == len(LIVE_BASIC_REQUIRED_FIELDS)
    effective_age_seconds = max(ages_seconds.values()) if complete else None
    return LiveFieldFreshness(
        observed_at=observed_at,
        ages_seconds=ages_seconds,
        effective_age_seconds=effective_age_seconds,
        complete=complete,
    )
