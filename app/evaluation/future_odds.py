from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.jobs import JobType
from app.jobs.repository import JobRepository
from app.models import DecisionFutureOdds, DecisionSnapshotRecord, OddsObservationRecord


class FutureOddsService:
    def __init__(self, jobs: JobRepository) -> None:
        self._jobs = jobs

    async def schedule(
        self,
        session: AsyncSession,
        *,
        snapshot_id: UUID,
        decision_at: datetime,
        horizons_seconds: tuple[int, ...],
    ) -> int:
        scheduled = 0
        for horizon in horizons_seconds:
            if horizon <= 0:
                raise ValueError("future odds horizons must be positive")
            due_at = decision_at + timedelta(seconds=horizon)
            await self._jobs.enqueue(
                session,
                job_type=JobType.CAPTURE_FUTURE_ODDS,
                dedupe_key=f"future-odds:{snapshot_id}:{horizon}",
                payload={
                    "snapshot_id": str(snapshot_id),
                    "horizon_seconds": horizon,
                    "due_at": due_at.isoformat(),
                },
                not_before=due_at,
            )
            scheduled += 1
        return scheduled

    async def capture(
        self,
        session: AsyncSession,
        *,
        snapshot_id: UUID,
        horizon_seconds: int,
        due_at: datetime,
        observed_at: datetime,
    ) -> DecisionFutureOdds:
        existing = await session.scalar(
            select(DecisionFutureOdds).where(
                DecisionFutureOdds.decision_snapshot_id == snapshot_id,
                DecisionFutureOdds.horizon_seconds == horizon_seconds,
                DecisionFutureOdds.due_at == due_at,
            )
        )
        if existing is not None:
            return existing
        snapshot = await session.get(DecisionSnapshotRecord, snapshot_id)
        if snapshot is None:
            raise ValueError("decision snapshot does not exist")
        observations = snapshot.canonical_payload.get("market", {}).get("observations", [])
        odds_ids = [item.get("odds_id") for item in observations if isinstance(item, dict)]
        captured: list[OddsObservationRecord] = []
        for odds_id in odds_ids:
            if not isinstance(odds_id, int):
                continue
            observation = await session.scalar(
                select(OddsObservationRecord)
                .where(
                    OddsObservationRecord.odds_id == odds_id,
                    OddsObservationRecord.received_at >= due_at,
                    OddsObservationRecord.received_at <= observed_at,
                )
                .order_by(OddsObservationRecord.received_at)
                .limit(1)
            )
            if observation is not None:
                captured.append(observation)
        captured.sort(key=lambda item: odds_ids.index(item.odds_id))
        complete = len(captured) == 2
        record = DecisionFutureOdds(
            decision_snapshot_id=snapshot_id,
            horizon_seconds=horizon_seconds,
            due_at=due_at,
            observed_at=(max(item.received_at for item in captured) if complete else observed_at),
            odds_a=captured[0].price if complete else None,
            odds_b=captured[1].price if complete else None,
            status="CAPTURED" if complete else "MISSING",
        )
        session.add(record)
        await session.flush()
        return record
