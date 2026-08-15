from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.jobs import ai_job_dedupe_key_for_experiment, ai_job_payload
from app.domain.jobs import JobType
from app.jobs.repository import JobRepository
from app.models import AiDecisionRecord, DecisionSnapshotRecord, DurableJobRecord


class AiExperimentReplayService:
    """Explicitly enqueue historical AI experiment replays.

    Production reconciliation must not infer a new historical experiment merely
    because prompt/policy/view versions changed. Replay is an explicit action:
    callers choose the snapshots/range and the experiment identities to run.
    Replay jobs are marked so persistence remains auditable but runtime health
    and decision notifications are not affected by historical experiments.

    Experiment identities must describe the currently configured code/provider
    experiments. This service selects *which historical snapshots* to replay;
    it does not emulate an old or future prompt implementation by itself.
    """

    def __init__(
        self,
        jobs: JobRepository,
        *,
        experiments: tuple[tuple[str, str, str, str, str], ...],
        priority: int = 160,
    ) -> None:
        self._jobs = jobs
        self._experiments = experiments
        self._priority = priority

    async def enqueue_snapshots(
        self,
        session: AsyncSession,
        *,
        snapshot_ids: Sequence[UUID],
    ) -> int:
        if not snapshot_ids or not self._experiments:
            return 0
        snapshots = list(
            (
                await session.scalars(
                    select(DecisionSnapshotRecord)
                    .where(DecisionSnapshotRecord.id.in_(tuple(snapshot_ids)))
                    .order_by(DecisionSnapshotRecord.decision_at.asc())
                )
            ).all()
        )
        return await self._enqueue_records(session, snapshots)

    async def enqueue_range(
        self,
        session: AsyncSession,
        *,
        decision_from: datetime | None = None,
        decision_to: datetime | None = None,
        limit: int | None = None,
    ) -> int:
        query = select(DecisionSnapshotRecord)
        if decision_from is not None:
            query = query.where(DecisionSnapshotRecord.decision_at >= decision_from)
        if decision_to is not None:
            query = query.where(DecisionSnapshotRecord.decision_at <= decision_to)
        query = query.order_by(DecisionSnapshotRecord.decision_at.asc())
        if limit is not None:
            if limit < 1:
                raise ValueError("limit must be positive")
            query = query.limit(limit)
        snapshots = list((await session.scalars(query)).all())
        return await self._enqueue_records(session, snapshots)

    async def _enqueue_records(
        self,
        session: AsyncSession,
        snapshots: Sequence[DecisionSnapshotRecord],
    ) -> int:
        created = 0
        for snapshot in snapshots:
            for experiment in self._experiments:
                provider, model, prompt_version, policy_version, ai_view_version = experiment
                existing_record = await session.scalar(
                    select(AiDecisionRecord.id).where(
                        AiDecisionRecord.snapshot_id == snapshot.id,
                        AiDecisionRecord.provider == provider,
                        AiDecisionRecord.model == model,
                        AiDecisionRecord.prompt_version == prompt_version,
                        AiDecisionRecord.decision_policy_version == policy_version,
                        AiDecisionRecord.ai_view_version == ai_view_version,
                    )
                )
                if existing_record is not None:
                    continue
                dedupe_key = ai_job_dedupe_key_for_experiment(
                    snapshot.snapshot_hash,
                    experiment,
                )
                existing_job = await session.scalar(
                    select(DurableJobRecord.id).where(
                        DurableJobRecord.job_type == JobType.RUN_AI_PROVIDER.value,
                        DurableJobRecord.dedupe_key == dedupe_key,
                    )
                )
                if existing_job is not None:
                    continue
                payload = ai_job_payload(snapshot.id, provider, model)
                payload["experiment_replay"] = True
                await self._jobs.enqueue(
                    session,
                    job_type=JobType.RUN_AI_PROVIDER,
                    dedupe_key=dedupe_key,
                    payload=payload,
                    priority=self._priority,
                )
                created += 1
        return created
