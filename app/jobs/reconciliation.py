from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.jobs import JobType
from app.jobs.repository import JobRepository
from app.models import (
    AiDecisionRecord,
    DecisionEvaluationRecord,
    DecisionFutureOdds,
    DecisionSnapshotRecord,
    DomainEventRecord,
    DraftMinuteCurveRecord,
    DraftSnapshotRecord,
    HistoricalMapRecord,
    MapResultRecord,
)


@dataclass(frozen=True)
class ReconciliationResult:
    reclaimed_jobs: int
    draft_jobs: int
    ai_jobs: int
    future_odds_jobs: int
    settlement_jobs: int
    evaluation_jobs: int


class ReconciliationService:
    def __init__(
        self,
        jobs: JobRepository,
        *,
        lease_seconds: float,
        ai_experiments: tuple[tuple[str, str, str, str], ...],
        future_odds_horizons: tuple[int, ...],
    ) -> None:
        self._jobs = jobs
        self._lease_seconds = lease_seconds
        self._ai_experiments = ai_experiments
        self._future_odds_horizons = future_odds_horizons

    async def run(self, session: AsyncSession, *, now: datetime) -> ReconciliationResult:
        reclaimed = await self._jobs.reclaim_expired(
            session, lease_seconds=self._lease_seconds, now=now
        )
        draft_jobs = await self._reconcile_drafts(session)
        ai_jobs = await self._reconcile_ai(session)
        future_jobs = await self._reconcile_future_odds(session)
        settlement_jobs = await self._reconcile_settlements(session)
        evaluation_jobs = await self._reconcile_evaluations(session)
        return ReconciliationResult(
            reclaimed_jobs=reclaimed,
            draft_jobs=draft_jobs,
            ai_jobs=ai_jobs,
            future_odds_jobs=future_jobs,
            settlement_jobs=settlement_jobs,
            evaluation_jobs=evaluation_jobs,
        )

    async def _reconcile_drafts(self, session: AsyncSession) -> int:
        drafts = list(
            (
                await session.scalars(
                    select(DraftSnapshotRecord).where(DraftSnapshotRecord.complete.is_(True))
                )
            ).all()
        )
        created = 0
        for draft in drafts:
            curve = await session.scalar(
                select(DraftMinuteCurveRecord.id).where(
                    DraftMinuteCurveRecord.draft_snapshot_id == draft.id
                )
            )
            if curve is not None:
                continue
            await self._jobs.enqueue(
                session,
                job_type=JobType.BUILD_DRAFT_CURVE,
                dedupe_key=f"reconcile-draft:{draft.id}",
                payload={
                    "canonical_map_id": str(draft.canonical_map_id),
                    "draft_snapshot_id": str(draft.id),
                },
            )
            created += 1
        return created

    async def _reconcile_ai(self, session: AsyncSession) -> int:
        snapshots = list((await session.scalars(select(DecisionSnapshotRecord))).all())
        created = 0
        for snapshot in snapshots:
            completed = set(
                (
                    await session.scalars(
                        select(
                            AiDecisionRecord.provider,
                            AiDecisionRecord.model,
                            AiDecisionRecord.prompt_version,
                            AiDecisionRecord.decision_policy_version,
                        ).where(AiDecisionRecord.snapshot_id == snapshot.id)
                    )
                ).all()
            )
            if set(self._ai_experiments).issubset(completed):
                continue
            await self._jobs.enqueue(
                session,
                job_type=JobType.RUN_AI_PROVIDER,
                dedupe_key=f"reconcile-ai:{snapshot.id}",
                payload={"snapshot_id": str(snapshot.id)},
            )
            created += 1
        return created

    async def _reconcile_future_odds(self, session: AsyncSession) -> int:
        snapshots = list((await session.scalars(select(DecisionSnapshotRecord))).all())
        created = 0
        for snapshot in snapshots:
            captured = set(
                (
                    await session.scalars(
                        select(DecisionFutureOdds.horizon_seconds).where(
                            DecisionFutureOdds.decision_snapshot_id == snapshot.id,
                            DecisionFutureOdds.capture_type == "TIME_HORIZON",
                        )
                    )
                ).all()
            )
            for horizon in self._future_odds_horizons:
                if horizon in captured:
                    continue
                due_at = snapshot.decision_at + timedelta(seconds=horizon)
                await self._jobs.enqueue(
                    session,
                    job_type=JobType.CAPTURE_FUTURE_ODDS,
                    dedupe_key=f"future-odds:{snapshot.id}:{horizon}",
                    payload={
                        "snapshot_id": str(snapshot.id),
                        "capture_type": "TIME_HORIZON",
                        "horizon_seconds": horizon,
                        "due_at": due_at.isoformat(),
                    },
                    not_before=due_at,
                )
                created += 1
            if snapshot.canonical_map_id is None:
                continue
            map_started_at = await session.scalar(
                select(DomainEventRecord.occurred_at)
                .where(
                    DomainEventRecord.event_type == "MAP_STARTED",
                    DomainEventRecord.aggregate_id == str(snapshot.canonical_map_id),
                )
                .order_by(DomainEventRecord.occurred_at)
                .limit(1)
            )
            if map_started_at is None:
                continue
            closing_exists = await session.scalar(
                select(DecisionFutureOdds.id).where(
                    DecisionFutureOdds.decision_snapshot_id == snapshot.id,
                    DecisionFutureOdds.capture_type == "CLOSING",
                )
            )
            if closing_exists is not None:
                continue
            await self._jobs.enqueue(
                session,
                job_type=JobType.CAPTURE_FUTURE_ODDS,
                dedupe_key=f"closing-odds:{snapshot.id}",
                payload={
                    "snapshot_id": str(snapshot.id),
                    "capture_type": "CLOSING",
                    "triggered_at": map_started_at.isoformat(),
                },
                not_before=map_started_at,
            )
            created += 1
        return created

    async def _reconcile_settlements(self, session: AsyncSession) -> int:
        facts = list(
            (
                await session.scalars(
                    select(HistoricalMapRecord).where(
                        HistoricalMapRecord.canonical_map_id.is_not(None),
                        HistoricalMapRecord.winner_team_id.is_not(None),
                        HistoricalMapRecord.sync_status != "DATA_CONFLICT",
                    )
                )
            ).all()
        )
        created = 0
        for fact in facts:
            settled = await session.scalar(
                select(MapResultRecord.id).where(
                    MapResultRecord.canonical_map_id == fact.canonical_map_id
                )
            )
            if settled is not None:
                continue
            await self._jobs.enqueue(
                session,
                job_type=JobType.SETTLE_MAP,
                dedupe_key=f"reconcile-settlement:{fact.canonical_map_id}",
                payload={"canonical_map_id": str(fact.canonical_map_id)},
            )
            created += 1
        return created

    async def _reconcile_evaluations(self, session: AsyncSession) -> int:
        decisions = list((await session.scalars(select(AiDecisionRecord))).all())
        created_snapshots: set = set()
        for decision in decisions:
            snapshot = await session.get(DecisionSnapshotRecord, decision.snapshot_id)
            if snapshot is None or snapshot.canonical_map_id is None:
                continue
            result = await session.scalar(
                select(MapResultRecord.id).where(
                    MapResultRecord.canonical_map_id == snapshot.canonical_map_id,
                    MapResultRecord.provider_conflict.is_(False),
                    MapResultRecord.winner_team_id.is_not(None),
                )
            )
            evaluation = await session.scalar(
                select(DecisionEvaluationRecord.id).where(
                    DecisionEvaluationRecord.ai_decision_id == decision.id
                )
            )
            if result is None or evaluation is not None or snapshot.id in created_snapshots:
                continue
            await self._jobs.enqueue(
                session,
                job_type=JobType.EVALUATE_DECISION,
                dedupe_key=f"reconcile-evaluation:{snapshot.id}",
                payload={"snapshot_id": str(snapshot.id)},
            )
            created_snapshots.add(snapshot.id)
        return len(created_snapshots)
