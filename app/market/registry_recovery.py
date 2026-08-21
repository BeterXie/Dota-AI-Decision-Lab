from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.jobs import JobType
from app.jobs.repository import JobRepository
from app.models import CanonicalSeries, ProviderMatchMapping

RAYBET_RECOVERY_LOOKBACK = timedelta(hours=12)
RAYBET_RECOVERY_LOOKAHEAD = timedelta(hours=2)


async def enqueue_recent_raybet_registry_refreshes(
    session: AsyncSession,
    *,
    jobs: JobRepository,
    connected_at: datetime,
) -> int:
    """Bootstrap mapped current markets after a RayBet socket connection.

    SocketCluster only publishes changes, so reconnecting cannot recover prices
    missed while a connection was stale.  The HTTP bootstrap is durable work and
    is limited to recently started or imminent canonical series.
    """

    provider_match_ids = list(
        (
            await session.scalars(
                select(ProviderMatchMapping.provider_match_id)
                .join(
                    CanonicalSeries,
                    CanonicalSeries.id == ProviderMatchMapping.canonical_series_id,
                )
                .where(
                    ProviderMatchMapping.provider == "raybet",
                    CanonicalSeries.scheduled_at >= connected_at - RAYBET_RECOVERY_LOOKBACK,
                    CanonicalSeries.scheduled_at <= connected_at + RAYBET_RECOVERY_LOOKAHEAD,
                )
                .distinct()
                .order_by(ProviderMatchMapping.provider_match_id)
            )
        ).all()
    )
    minute_bucket = connected_at.strftime("%Y%m%d%H%M")
    enqueued = 0
    for provider_match_id in provider_match_ids:
        try:
            numeric_match_id = int(provider_match_id)
        except ValueError:
            continue
        await jobs.enqueue(
            session,
            job_type=JobType.REFRESH_ODDS_REGISTRY,
            dedupe_key=f"raybet-socket-recovery:{numeric_match_id}:{minute_bucket}",
            payload={
                "provider_match_id": numeric_match_id,
                "trigger": "RAYBET_SOCKET_CONNECTED",
            },
            priority=50,
        )
        enqueued += 1
    return enqueued
