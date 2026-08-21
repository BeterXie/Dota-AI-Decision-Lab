from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import String, and_, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.eligibility import ai_record_is_game_time_eligible
from app.ai.jobs import ai_job_dedupe_key_for_experiment, ai_job_payload
from app.domain.events import DomainEvent, DomainEventType
from app.domain.jobs import JobStatus, JobType
from app.draft.engine import MODEL_VERSION
from app.evaluation.metrics import METRICS_VERSION
from app.events.outbox import EventRepository
from app.jobs.repository import JobRepository
from app.live.anchor import picks_ended_anchor
from app.models import (
    AiDecisionRecord,
    CanonicalMap,
    CanonicalTeam,
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
    ProviderRawEvent,
    ProviderTeamMapping,
)
from app.runtime_config import active_ai_experiments
from app.time import ensure_utc


@dataclass(frozen=True)
class ReconciliationResult:
    reclaimed_jobs: int
    draft_jobs: int
    snapshot_jobs: int
    ai_jobs: int
    future_odds_jobs: int
    postmatch_jobs: int
    settlement_jobs: int
    evaluation_jobs: int
    checkpoint_sweep_jobs: int = 0
    map_started_events: int = 0
    dltv_identity_recovery_jobs: int = 0


class ReconciliationService:
    def __init__(
        self,
        jobs: JobRepository,
        events: EventRepository,
        *,
        lease_seconds: float,
        ai_experiments: tuple[tuple[str, str, str, str, str], ...],
        future_odds_horizons: tuple[int, ...],
        ai_min_game_time_seconds: int = 600,
        checkpoint_minutes: tuple[int, ...] = (10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60),
        live_state_max_age_seconds: float = 120.0,
        checkpoint_sweep_grace_seconds: float = 300.0,
    ) -> None:
        self._jobs = jobs
        self._events = events
        self._lease_seconds = lease_seconds
        self._ai_experiments = ai_experiments
        self._future_odds_horizons = future_odds_horizons
        self._ai_min_game_time_seconds = ai_min_game_time_seconds
        self._checkpoint_minutes = checkpoint_minutes
        self._live_state_max_age_seconds = live_state_max_age_seconds
        self._checkpoint_sweep_grace_seconds = checkpoint_sweep_grace_seconds

    async def run(self, session: AsyncSession, *, now: datetime) -> ReconciliationResult:
        self._ai_experiments = await active_ai_experiments(session, self._ai_experiments)
        reclaimed = await self._jobs.reclaim_expired(
            session, lease_seconds=self._lease_seconds, now=now
        )
        dltv_identity_recovery_jobs = await self._reconcile_dltv_identity_conflicts(
            session, now=now
        )
        map_started_events = await self._reconcile_map_started_events(session)
        checkpoint_sweep_jobs = await self._reconcile_live_checkpoints(session, now=now)
        draft_jobs = await self._reconcile_drafts(session)
        snapshot_jobs = await self._reconcile_snapshots(session, now=now)
        ai_jobs = await self._reconcile_ai(session, now=now)
        future_jobs = await self._reconcile_future_odds(session, now=now)
        postmatch_jobs = await self._reconcile_postmatch(session, now=now)
        settlement_jobs = await self._reconcile_settlements(session)
        evaluation_jobs = await self._reconcile_evaluations(session)
        return ReconciliationResult(
            reclaimed_jobs=reclaimed,
            draft_jobs=draft_jobs,
            snapshot_jobs=snapshot_jobs,
            ai_jobs=ai_jobs,
            future_odds_jobs=future_jobs,
            postmatch_jobs=postmatch_jobs,
            settlement_jobs=settlement_jobs,
            evaluation_jobs=evaluation_jobs,
            checkpoint_sweep_jobs=checkpoint_sweep_jobs,
            map_started_events=map_started_events,
            dltv_identity_recovery_jobs=dltv_identity_recovery_jobs,
        )

    async def _reconcile_dltv_identity_conflicts(
        self,
        session: AsyncSession,
        *,
        now: datetime,
    ) -> int:
        failed_jobs = list(
            (
                await session.scalars(
                    select(DurableJobRecord)
                    .where(
                        DurableJobRecord.job_type == JobType.BOOTSTRAP_DLTV_MATCH.value,
                        DurableJobRecord.status == JobStatus.FAILED_TERMINAL.value,
                        ~DurableJobRecord.dedupe_key.like("reconcile-dltv-identity-v1:%"),
                        DurableJobRecord.last_error.contains(
                            "IdentityAmbiguousError: PROVIDER_EVENT_IDENTITY_CONFLICT"
                        ),
                        DurableJobRecord.completed_at >= now - timedelta(hours=24),
                    )
                    .order_by(DurableJobRecord.completed_at.desc())
                    .limit(100)
                )
            ).all()
        )
        jobs_by_provider_key: dict[str, DurableJobRecord] = {}
        for job in failed_jobs:
            valve_match_id = job.payload.get("valve_match_id")
            if isinstance(valve_match_id, int) and valve_match_id > 0:
                jobs_by_provider_key.setdefault(f"__nd2_match_{valve_match_id}", job)
        if not jobs_by_provider_key:
            return 0

        fresh_provider_keys = set(
            (
                await session.scalars(
                    select(ProviderRawEvent.provider_key)
                    .where(
                        ProviderRawEvent.provider == "dltv",
                        ProviderRawEvent.event_type == "DLTV_FAST_SOCKET",
                        ProviderRawEvent.provider_key.in_(tuple(jobs_by_provider_key)),
                        ProviderRawEvent.received_at
                        >= now - timedelta(seconds=self._live_state_max_age_seconds),
                    )
                    .distinct()
                    .limit(100)
                )
            ).all()
        )
        recoverable_jobs = [
            jobs_by_provider_key[provider_key]
            for provider_key in fresh_provider_keys
            if provider_key is not None
        ]
        if not recoverable_jobs:
            return 0

        recovery_keys = {job.id: f"reconcile-dltv-identity-v1:{job.id}" for job in recoverable_jobs}
        existing_keys = set(
            (
                await session.scalars(
                    select(DurableJobRecord.dedupe_key).where(
                        DurableJobRecord.job_type == JobType.BOOTSTRAP_DLTV_MATCH.value,
                        DurableJobRecord.dedupe_key.in_(recovery_keys.values()),
                    )
                )
            ).all()
        )

        created = 0
        for job in recoverable_jobs:
            dedupe_key = recovery_keys[job.id]
            if dedupe_key in existing_keys:
                continue
            await self._jobs.enqueue(
                session,
                job_type=JobType.BOOTSTRAP_DLTV_MATCH,
                dedupe_key=dedupe_key,
                payload=dict(job.payload),
                priority=job.priority,
                not_before=now,
            )
            created += 1
        return created

    async def _reconcile_map_started_events(self, session: AsyncSession) -> int:
        canonical_map_text = func.replace(
            cast(DltvLiveObservationRecord.canonical_map_id, String), "-", ""
        )
        missing_started_event = (
            ~select(DomainEventRecord.id)
            .where(
                DomainEventRecord.event_type == DomainEventType.MAP_STARTED.value,
                func.replace(DomainEventRecord.aggregate_id, "-", "") == canonical_map_text,
            )
            .exists()
        )
        rows = list(
            (
                await session.execute(
                    select(
                        DltvLiveObservationRecord.canonical_map_id,
                        func.min(DltvLiveObservationRecord.received_at),
                    )
                    .where(
                        DltvLiveObservationRecord.canonical_map_id.is_not(None),
                        DltvLiveObservationRecord.game_time_seconds > 0,
                        missing_started_event,
                    )
                    .group_by(DltvLiveObservationRecord.canonical_map_id)
                    .order_by(func.min(DltvLiveObservationRecord.received_at))
                    .limit(500)
                )
            ).all()
        )
        for canonical_map_id, first_positive_at in rows:
            await self._events.record(
                session,
                DomainEvent(
                    event_type=DomainEventType.MAP_STARTED,
                    aggregate_type="canonical_map",
                    aggregate_id=str(canonical_map_id),
                    dedupe_key=f"map-started:{canonical_map_id}",
                    payload={"canonical_map_id": str(canonical_map_id)},
                    occurred_at=first_positive_at,
                ),
            )
        return len(rows)

    async def _reconcile_live_checkpoints(self, session: AsyncSession, *, now: datetime) -> int:
        """Close the trigger gap when the DLTV fast socket goes quiet.

        Checkpoints are normally recorded as DLTV fast-state messages arrive;
        the socket is event-driven, so during quiet mid-game stretches it can
        be minutes between messages and real-time checkpoints fire late. This
        sweeper fires crossed checkpoint minutes that are still inside the
        grace window for every LIVE map with a known real-start anchor. The
        domain-event dedupe key is identical to the collector's, so the two
        paths are idempotent with each other.
        """
        if not self._checkpoint_minutes:
            return 0
        cutoff = now - timedelta(seconds=self._live_state_max_age_seconds)
        live_map_ids = set(
            (
                await session.scalars(
                    select(DltvLiveObservationRecord.canonical_map_id)
                    .where(
                        DltvLiveObservationRecord.canonical_map_id.is_not(None),
                        DltvLiveObservationRecord.valve_match_id.is_not(None),
                        DltvLiveObservationRecord.received_at >= cutoff,
                    )
                    .distinct()
                )
            ).all()
        )
        created = 0
        for canonical_map_id in live_map_ids:
            canonical_map = await session.get(CanonicalMap, canonical_map_id)
            if canonical_map is None or canonical_map.valve_match_id is None:
                continue
            anchor = await picks_ended_anchor(
                session,
                valve_match_id=canonical_map.valve_match_id,
                decision_at=now,
            )
            if anchor is None:
                continue
            elapsed_seconds = (now - ensure_utc(anchor)).total_seconds()
            if elapsed_seconds < self._checkpoint_minutes[0] * 60:
                continue
            recorded = list(
                (
                    await session.scalars(
                        select(DomainEventRecord.payload).where(
                            DomainEventRecord.event_type
                            == DomainEventType.DECISION_CHECKPOINT_DUE.value,
                            DomainEventRecord.aggregate_id == str(canonical_map.id),
                        )
                    )
                ).all()
            )
            recorded_minutes = {
                int(payload["checkpoint_minute"])
                for payload in recorded
                if isinstance(payload, dict) and isinstance(payload.get("checkpoint_minute"), int)
            }
            due_minutes = []
            for minute in self._checkpoint_minutes:
                if minute in recorded_minutes:
                    continue
                crossed_seconds = elapsed_seconds - minute * 60
                if 0 <= crossed_seconds <= self._checkpoint_sweep_grace_seconds:
                    due_minutes.append(minute)
            if not recorded_minutes and due_minutes:
                due_minutes = [due_minutes[-1]]
            for minute in due_minutes:
                await self._events.record(
                    session,
                    DomainEvent(
                        event_type=DomainEventType.DECISION_CHECKPOINT_DUE,
                        aggregate_type="canonical_map",
                        aggregate_id=str(canonical_map.id),
                        dedupe_key=f"checkpoint:{canonical_map.id}:{minute}",
                        payload={
                            "canonical_map_id": str(canonical_map.id),
                            "decision_at": now.isoformat(),
                            "checkpoint_minute": minute,
                            "basis": "real_time",
                        },
                        occurred_at=now,
                    ),
                )
                created += 1
        return created

    async def _reconcile_drafts(self, session: AsyncSession) -> int:
        drafts = list(
            (
                await session.scalars(
                    select(DraftSnapshotRecord)
                    .where(
                        DraftSnapshotRecord.complete.is_(True),
                        ~select(DraftMinuteCurveRecord.id)
                        .where(
                            DraftMinuteCurveRecord.draft_snapshot_id == DraftSnapshotRecord.id,
                            DraftMinuteCurveRecord.model_version == MODEL_VERSION,
                        )
                        .exists(),
                    )
                    .order_by(DraftSnapshotRecord.observed_at.desc())
                    .limit(1000)
                )
            ).all()
        )
        for draft in drafts:
            await self._jobs.enqueue(
                session,
                job_type=JobType.BUILD_DRAFT_CURVE,
                dedupe_key=f"reconcile-draft:{MODEL_VERSION}:{draft.id}",
                payload={
                    "canonical_map_id": str(draft.canonical_map_id),
                    "draft_snapshot_id": str(draft.id),
                },
                reopen_terminal=True,
            )
        return len(drafts)

    async def _reconcile_postmatch(self, session: AsyncSession, *, now: datetime) -> int:
        latest_live = (
            select(
                DltvLiveObservationRecord.canonical_map_id,
                func.max(DltvLiveObservationRecord.received_at).label("latest_received_at"),
            )
            .where(DltvLiveObservationRecord.canonical_map_id.is_not(None))
            .group_by(DltvLiveObservationRecord.canonical_map_id)
            .subquery()
        )
        generated_placeholder_ids = (
            select(ProviderTeamMapping.canonical_team_id)
            .join(
                CanonicalTeam,
                CanonicalTeam.id == ProviderTeamMapping.canonical_team_id,
            )
            .where(
                CanonicalTeam.name
                == func.upper(ProviderTeamMapping.provider)
                + " team "
                + ProviderTeamMapping.provider_team_id
            )
        )
        missing_result = (
            ~select(MapResultRecord.id)
            .where(MapResultRecord.canonical_map_id == CanonicalMap.id)
            .exists()
        )
        conflicted_result = (
            select(MapResultRecord.id)
            .where(
                MapResultRecord.canonical_map_id == CanonicalMap.id,
                or_(
                    MapResultRecord.winner_team_id.is_(None),
                    MapResultRecord.provider_conflict.is_(True),
                ),
            )
            .exists()
        )
        repairable_placeholder = (
            select(HistoricalMapRecord.id)
            .where(
                HistoricalMapRecord.canonical_map_id == CanonicalMap.id,
                or_(
                    HistoricalMapRecord.radiant_team_id.in_(generated_placeholder_ids),
                    HistoricalMapRecord.dire_team_id.in_(generated_placeholder_ids),
                    HistoricalMapRecord.winner_team_id.in_(generated_placeholder_ids),
                ),
            )
            .exists()
        )
        candidates = list(
            (
                await session.execute(
                    select(
                        CanonicalMap.id,
                        CanonicalMap.valve_match_id,
                        latest_live.c.latest_received_at,
                    )
                    .select_from(CanonicalMap)
                    .join(
                        latest_live,
                        latest_live.c.canonical_map_id == CanonicalMap.id,
                    )
                    .where(
                        CanonicalMap.valve_match_id.is_not(None),
                        select(ProviderMatchMapping.id)
                        .where(
                            ProviderMatchMapping.provider == "raybet",
                            ProviderMatchMapping.canonical_series_id == CanonicalMap.series_id,
                        )
                        .exists(),
                        latest_live.c.latest_received_at < now - timedelta(minutes=3),
                        or_(
                            and_(
                                latest_live.c.latest_received_at >= now - timedelta(days=2),
                                missing_result,
                            ),
                            and_(conflicted_result, repairable_placeholder),
                        ),
                    )
                    .limit(500)
                )
            ).all()
        )
        bucket = int(now.timestamp()) // 900
        created = 0
        for canonical_map_id, valve_match_id, _latest_received_at in candidates:
            dedupe_key = f"reconcile-postmatch-v3:{canonical_map_id}:{bucket}"
            existing = await session.scalar(
                select(DurableJobRecord.id).where(
                    DurableJobRecord.job_type == JobType.RESOLVE_POSTMATCH.value,
                    DurableJobRecord.dedupe_key == dedupe_key,
                )
            )
            if existing is not None:
                continue
            await self._jobs.enqueue(
                session,
                job_type=JobType.RESOLVE_POSTMATCH,
                dedupe_key=dedupe_key,
                payload={
                    "canonical_map_id": str(canonical_map_id),
                    "valve_match_id": valve_match_id,
                },
                priority=80,
                max_attempts=10,
            )
            created += 1
        return created

    async def _reconcile_snapshots(self, session: AsyncSession, *, now: datetime) -> int:
        """Requeue processed snapshot triggers that produced no snapshot.

        A provider identity merge can make an earlier, correctly failed
        BUILD_SNAPSHOT job eligible on replay (for example, the market and
        DLTV map used to point at different canonical series). The original
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
                checkpoint_snapshot = await session.scalar(
                    select(DecisionSnapshotRecord.id)
                    .where(
                        DecisionSnapshotRecord.canonical_map_id == map_id_value,
                        DecisionSnapshotRecord.decision_at == decision_at_value,
                    )
                    .limit(1)
                )
                if checkpoint_snapshot is not None:
                    continue
                market_team_count = await session.scalar(
                    select(
                        func.count(func.distinct(OddsObservationRecord.selection_team_id))
                    ).where(
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
                job_payload = {
                    "canonical_map_id": canonical_map_id,
                    "canonical_series_id": payload.get("canonical_series_id"),
                    "decision_at": decision_at_value.isoformat(),
                    "reconciliation_event_id": str(event.id),
                }
                if existing is not None:
                    if existing.status in {"PENDING", "RUNNING", "RETRY_WAIT"}:
                        break
                    if existing.status == JobStatus.FAILED_TERMINAL.value:
                        await self._jobs.enqueue(
                            session,
                            job_type=JobType.BUILD_SNAPSHOT,
                            dedupe_key=dedupe_key,
                            payload=job_payload,
                            reopen_terminal=True,
                        )
                        created += 1
                        break
                    continue
                await self._jobs.enqueue(
                    session,
                    job_type=JobType.BUILD_SNAPSHOT,
                    dedupe_key=dedupe_key,
                    payload=job_payload,
                )
                created += 1
                break
        return created

    async def _reconcile_ai(self, session: AsyncSession, *, now: datetime) -> int:
        """Recover each missing provider for recent, game-time-eligible snapshots."""
        if not self._ai_experiments:
            return 0
        snapshots = list(
            (
                await session.scalars(
                    select(DecisionSnapshotRecord)
                    .where(DecisionSnapshotRecord.decision_at >= now - timedelta(hours=24))
                    .order_by(DecisionSnapshotRecord.decision_at.asc())
                    .limit(1000)
                )
            ).all()
        )
        created = 0
        for snapshot in snapshots:
            if not ai_record_is_game_time_eligible(
                snapshot.canonical_payload,
                min_game_time_seconds=self._ai_min_game_time_seconds,
            ):
                continue
            record_keys = {
                (
                    row.provider,
                    row.model,
                    row.prompt_version,
                    row.decision_policy_version,
                    row.ai_view_version,
                )
                for row in (
                    await session.execute(
                        select(
                            AiDecisionRecord.provider,
                            AiDecisionRecord.model,
                            AiDecisionRecord.prompt_version,
                            AiDecisionRecord.decision_policy_version,
                            AiDecisionRecord.ai_view_version,
                        ).where(AiDecisionRecord.snapshot_id == snapshot.id)
                    )
                ).all()
            }
            existing_jobs = list(
                (
                    await session.scalars(
                        select(DurableJobRecord).where(
                            DurableJobRecord.job_type == JobType.RUN_AI_PROVIDER.value,
                            DurableJobRecord.dedupe_key.like(f"ai:{snapshot.snapshot_hash}%"),
                        )
                    )
                ).all()
            )
            by_key = {job.dedupe_key: job for job in existing_jobs}
            # Backfill each missing provider independently. One provider may
            # already have a record or job while another was enabled later.
            for experiment in self._ai_experiments:
                if experiment in record_keys:
                    continue
                provider, model = experiment[:2]
                dedupe_key = ai_job_dedupe_key_for_experiment(snapshot.snapshot_hash, experiment)
                existing = by_key.get(dedupe_key)
                if existing is None:
                    await self._jobs.enqueue(
                        session,
                        job_type=JobType.RUN_AI_PROVIDER,
                        dedupe_key=dedupe_key,
                        payload=ai_job_payload(snapshot.id, provider, model),
                        priority=150,
                    )
                    created += 1
                elif existing.status == JobStatus.FAILED_TERMINAL.value:
                    await self._jobs.enqueue(
                        session,
                        job_type=JobType.RUN_AI_PROVIDER,
                        dedupe_key=dedupe_key,
                        payload=ai_job_payload(snapshot.id, provider, model),
                        priority=150,
                        reopen_terminal=True,
                    )
                    created += 1
        return created

    async def _reconcile_future_odds(self, session: AsyncSession, *, now: datetime) -> int:
        """Recover recent live captures without turning MISSING into a permanent tombstone."""
        snapshots = list(
            (
                await session.scalars(
                    select(DecisionSnapshotRecord)
                    .where(DecisionSnapshotRecord.decision_at >= now - timedelta(hours=12))
                    .order_by(DecisionSnapshotRecord.decision_at.asc())
                    .limit(1000)
                )
            ).all()
        )
        if not snapshots:
            return 0
        snapshot_ids = [item.id for item in snapshots]
        rows = list(
            (
                await session.scalars(
                    select(DecisionFutureOdds).where(
                        DecisionFutureOdds.decision_snapshot_id.in_(snapshot_ids)
                    )
                )
            ).all()
        )
        by_snapshot: dict[UUID, list[DecisionFutureOdds]] = {}
        for row in rows:
            by_snapshot.setdefault(row.decision_snapshot_id, []).append(row)

        retry_window = timedelta(minutes=30)
        bucket = int(now.timestamp()) // 300
        map_end_cache: dict[UUID, datetime | None] = {}
        created = 0
        for snapshot in snapshots:
            captures = by_snapshot.get(snapshot.id, [])
            for horizon in self._future_odds_horizons:
                due_at = snapshot.decision_at + timedelta(seconds=horizon)
                existing = next(
                    (
                        item
                        for item in captures
                        if item.capture_type == "TIME_HORIZON"
                        and item.horizon_seconds == horizon
                        and item.due_at == due_at
                    ),
                    None,
                )
                if existing is not None and existing.status == "CAPTURED":
                    continue
                if now > due_at + retry_window:
                    continue
                dedupe_key = (
                    f"future-odds-retry:{snapshot.id}:{horizon}:{bucket}"
                    if existing is not None and existing.status == "MISSING" and now >= due_at
                    else f"future-odds:{snapshot.id}:{horizon}"
                )
                await self._jobs.enqueue(
                    session,
                    job_type=JobType.CAPTURE_FUTURE_ODDS,
                    dedupe_key=dedupe_key,
                    payload={
                        "snapshot_id": str(snapshot.id),
                        "capture_type": "TIME_HORIZON",
                        "horizon_seconds": horizon,
                        "due_at": due_at.isoformat(),
                    },
                    not_before=max(due_at, now) if existing is not None else due_at,
                    reopen_terminal=True,
                )
                created += 1

            if snapshot.canonical_map_id is None:
                continue
            if snapshot.canonical_map_id not in map_end_cache:
                map_ended_at = await session.scalar(
                    select(DomainEventRecord.occurred_at)
                    .where(
                        DomainEventRecord.event_type == DomainEventType.MAP_ENDED.value,
                        DomainEventRecord.aggregate_id == str(snapshot.canonical_map_id),
                    )
                    .order_by(DomainEventRecord.occurred_at.asc())
                    .limit(1)
                )
                if map_ended_at is None:
                    map_ended_at = await session.scalar(
                        select(MapResultRecord.basic_first_usable_at).where(
                            MapResultRecord.canonical_map_id == snapshot.canonical_map_id
                        )
                    )
                map_end_cache[snapshot.canonical_map_id] = map_ended_at
            triggered_at = map_end_cache[snapshot.canonical_map_id]
            if triggered_at is None or triggered_at < snapshot.decision_at:
                continue
            closing = next(
                (item for item in captures if item.capture_type == "CLOSING"),
                None,
            )
            if closing is not None and closing.status == "CAPTURED":
                continue
            if now < triggered_at or now > triggered_at + retry_window:
                continue
            dedupe_key = (
                f"closing-odds-retry:{snapshot.id}:{bucket}"
                if closing is not None and closing.status == "MISSING"
                else f"closing-odds:{snapshot.id}"
            )
            await self._jobs.enqueue(
                session,
                job_type=JobType.CAPTURE_FUTURE_ODDS,
                dedupe_key=dedupe_key,
                payload={
                    "snapshot_id": str(snapshot.id),
                    "capture_type": "CLOSING",
                    "triggered_at": triggered_at.isoformat(),
                },
                not_before=max(triggered_at, now),
                reopen_terminal=True,
            )
            created += 1
        return created

    async def _reconcile_settlements(self, session: AsyncSession) -> int:
        facts = list(
            (
                await session.scalars(
                    select(HistoricalMapRecord)
                    .where(
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
                        ~select(MapResultRecord.id)
                        .where(
                            MapResultRecord.canonical_map_id == HistoricalMapRecord.canonical_map_id
                        )
                        .exists(),
                    )
                    .order_by(HistoricalMapRecord.first_usable_at.desc())
                    .limit(1000)
                )
            ).all()
        )
        for fact in facts:
            await self._jobs.enqueue(
                session,
                job_type=JobType.SETTLE_MAP,
                dedupe_key=f"reconcile-settlement:{fact.canonical_map_id}",
                payload={"canonical_map_id": str(fact.canonical_map_id)},
                reopen_terminal=True,
            )
        return len(facts)

    async def _reconcile_evaluations(self, session: AsyncSession) -> int:
        snapshot_ids = list(
            (
                await session.scalars(
                    select(DecisionSnapshotRecord.id)
                    .join(
                        AiDecisionRecord,
                        AiDecisionRecord.snapshot_id == DecisionSnapshotRecord.id,
                    )
                    .join(
                        MapResultRecord,
                        MapResultRecord.canonical_map_id == DecisionSnapshotRecord.canonical_map_id,
                    )
                    .where(
                        DecisionSnapshotRecord.canonical_map_id.is_not(None),
                        AiDecisionRecord.parse_status == "SUCCESS",
                        AiDecisionRecord.normalized_response.is_not(None),
                        MapResultRecord.provider_conflict.is_(False),
                        MapResultRecord.winner_team_id.is_not(None),
                        ~select(DecisionEvaluationRecord.id)
                        .where(
                            DecisionEvaluationRecord.ai_decision_id == AiDecisionRecord.id,
                            DecisionEvaluationRecord.metrics_version == METRICS_VERSION,
                        )
                        .exists(),
                    )
                    .distinct()
                    .order_by(DecisionSnapshotRecord.id)
                    .limit(1000)
                )
            ).all()
        )
        for snapshot_id in snapshot_ids:
            await self._jobs.enqueue(
                session,
                job_type=JobType.EVALUATE_DECISION,
                dedupe_key=f"reconcile-evaluation:{METRICS_VERSION}:{snapshot_id}",
                payload={"snapshot_id": str(snapshot_id)},
                reopen_terminal=True,
            )
        return len(snapshot_ids)
