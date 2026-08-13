from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.eligibility import ai_record_is_game_time_eligible
from app.domain.jobs import JobType
from app.draft.engine import MODEL_VERSION
from app.jobs.repository import JobRepository
from app.models import (
    AiDecisionRecord,
    DecisionEvaluationRecord,
    DecisionFutureOdds,
    DecisionSnapshotRecord,
    DltvLiveObservationRecord,
    DomainEventRecord,
    DraftMinuteCurveRecord,
    DraftSnapshotRecord,
    DurableJobRecord,
    HistoricalMapRecord,
    MapResultRecord,
    OddsObservationRecord,
    ProviderMatchMapping,
)
from app.time import ensure_utc


@dataclass(frozen=True)
class ReconciliationResult:
    reclaimed_jobs: int
    draft_jobs: int
    snapshot_jobs: int
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
        ai_min_game_time_seconds: int = 600,
    ) -> None:
        self._jobs = jobs
        self._lease_seconds = lease_seconds
        self._ai_experiments = ai_experiments
        self._future_odds_horizons = future_odds_horizons
        self._ai_min_game_time_seconds = ai_min_game_time_seconds

    async def run(self, session: AsyncSession, *, now: datetime) -> ReconciliationResult:
        reclaimed = await self._jobs.reclaim_expired(
            session, lease_seconds=self._lease_seconds, now=now
        )
        draft_jobs = await self._reconcile_drafts(session)
        snapshot_jobs = await self._reconcile_snapshots(session, now=now)
        ai_jobs = await self._reconcile_ai(session)
        future_jobs = await self._reconcile_future_odds(session)
        settlement_jobs = await self._reconcile_settlements(session)
        evaluation_jobs = await self._reconcile_evaluations(session)
        return ReconciliationResult(
            reclaimed_jobs=reclaimed,
            draft_jobs=draft_jobs,
            snapshot_jobs=snapshot_jobs,
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
                    DraftMinuteCurveRecord.draft_snapshot_id == draft.id,
                    DraftMinuteCurveRecord.model_version == MODEL_VERSION,
                )
            )
            if curve is not None:
                continue
            await self._jobs.enqueue(
                session,
                job_type=JobType.BUILD_DRAFT_CURVE,
                dedupe_key=f"reconcile-draft:{MODEL_VERSION}:{draft.id}",
                payload={
                    "canonical_map_id": str(draft.canonical_map_id),
                    "draft_snapshot_id": str(draft.id),
                },
            )
            created += 1
        return created

    async def _reconcile_snapshots(self, session: AsyncSession, *, now: datetime) -> int:
        """Requeue processed snapshot triggers that produced no snapshot.

        A provider identity merge can make an earlier, correctly failed
        BUILD_SNAPSHOT job eligible on replay (for example, the market and
        DLTV map used to point at different canonical series).  The original
        job must remain immutable for auditability, so reconciliation creates
        one durable replay job per trigger instead of mutating job history.
        """
        trigger_types = {"DECISION_CHECKPOINT_DUE"}
        events = list(
            (
                await session.scalars(
                    select(DomainEventRecord)
                    .where(
                        DomainEventRecord.event_type.in_(trigger_types),
                        DomainEventRecord.processed_at.is_not(None),
                        DomainEventRecord.occurred_at >= now - timedelta(hours=3),
                    )
                    .order_by(DomainEventRecord.occurred_at.desc())
                )
            ).all()
        )
        events_by_map: dict[str, list[DomainEventRecord]] = {}
        for event in events:
            map_id = (event.payload or {}).get("canonical_map_id")
            checkpoint = (event.payload or {}).get("checkpoint_minute")
            if not isinstance(map_id, str) or not isinstance(checkpoint, int) or checkpoint < 10:
                continue
            events_by_map.setdefault(map_id, []).append(event)

        created = 0
        for canonical_map_id, map_events in events_by_map.items():
            try:
                map_id_value = UUID(canonical_map_id)
            except ValueError:
                continue
            snapshot_exists = await session.scalar(
                select(DecisionSnapshotRecord.id)
                .where(DecisionSnapshotRecord.canonical_map_id == map_id_value)
                .limit(1)
            )
            if snapshot_exists is not None:
                continue
            live_at = await session.scalar(
                select(DltvLiveObservationRecord.received_at)
                .where(DltvLiveObservationRecord.canonical_map_id == map_id_value)
                .order_by(DltvLiveObservationRecord.received_at.desc())
                .limit(1)
            )
            if live_at is None or ensure_utc(live_at) < now - timedelta(hours=3):
                continue
            for event in map_events:
                payload = event.payload or {}
                decision_at = payload.get("decision_at")
                try:
                    decision_at_value = (
                        datetime.fromisoformat(decision_at).astimezone(UTC)
                        if isinstance(decision_at, str)
                        else ensure_utc(event.occurred_at)
                    )
                except ValueError:
                    continue
                market_team_count = await session.scalar(
                    select(func.count(func.distinct(OddsObservationRecord.selection_team_id))).where(
                        OddsObservationRecord.canonical_map_id == map_id_value,
                        OddsObservationRecord.market_type == "Winner",
                        OddsObservationRecord.selection_team_id.is_not(None),
                        OddsObservationRecord.received_at <= decision_at_value,
                    )
                )
                if (market_team_count or 0) < 2:
                    continue
                dedupe_key = f"reconcile-snapshot-v2:{event.id}"
                existing = await session.scalar(
                    select(DurableJobRecord).where(
                        DurableJobRecord.job_type == JobType.BUILD_SNAPSHOT.value,
                        DurableJobRecord.dedupe_key == dedupe_key,
                    )
                )
                if existing is not None:
                    if existing.status in {"PENDING", "RUNNING", "RETRY_WAIT"}:
                        break
                    continue
                await self._jobs.enqueue(
                    session,
                    job_type=JobType.BUILD_SNAPSHOT,
                    dedupe_key=dedupe_key,
                    payload={
                        "canonical_map_id": canonical_map_id,
                        "canonical_series_id": payload.get("canonical_series_id"),
                        "decision_at": decision_at_value.isoformat(),
                        "reconciliation_event_id": str(event.id),
                    },
                )
                created += 1
                break
        return created

    async def _reconcile_ai(self, session: AsyncSession) -> int:
        snapshots = list((await session.scalars(select(DecisionSnapshotRecord))).all())
        created = 0
        for snapshot in snapshots:
            if not ai_record_is_game_time_eligible(
                snapshot.canonical_payload,
                min_game_time_seconds=self._ai_min_game_time_seconds,
            ):
                continue
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
                        select(ProviderMatchMapping.id)
                        .where(
                            ProviderMatchMapping.provider == "raybet",
                            ProviderMatchMapping.canonical_map_id
                            == HistoricalMapRecord.canonical_map_id,
                        )
                        .exists(),
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
