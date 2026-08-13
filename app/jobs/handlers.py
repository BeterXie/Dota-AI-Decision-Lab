from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ai.coordinator import AiCoordinator
from app.ai.eligibility import ai_decision_is_game_time_eligible
from app.config import Settings
from app.domain.events import DomainEvent, DomainEventType
from app.domain.jobs import DurableJob, JobType
from app.draft.coordinator import DltvBootstrapCoordinator
from app.draft.rosh_service import RoshService
from app.evaluation.future_odds import FutureOddsService
from app.evaluation.metrics import EvaluationService
from app.evaluation.settlement import SettlementService
from app.events.outbox import EventRepository
from app.history.builder import HistoricalFeatureBuilder
from app.history.identity import HistoricalTeamResolver
from app.history.repository import HistoricalRepository
from app.history.sync import HistoricalSyncService
from app.market.registry_refresh import RayBetRegistryRefreshService
from app.models import (
    AiDecisionRecord,
    CanonicalMap,
    CanonicalSeries,
    DecisionSnapshotRecord,
    DraftSlotRecord,
    DraftSnapshotRecord,
    HistoricalMapRecord,
    MapResultRecord,
    ProviderMatchMapping,
    ProviderTeamMapping,
)
from app.notifications.email import DecisionEmailNotificationService
from app.providers.opendota.client import OpenDotaClient
from app.repositories.raw import RawEventRepository
from app.runtime.health import HealthRegistry
from app.snapshots.builder import SnapshotBuilder
from app.snapshots.repository import SnapshotRepository
from app.temporal.aligner import TemporalAligner
from app.time import ensure_utc


@dataclass(frozen=True)
class JobHandlerDependencies:
    settings: Settings
    health: HealthRegistry
    session_factory: async_sessionmaker[AsyncSession]
    events: EventRepository
    raw_events: RawEventRepository
    registry_refresh: RayBetRegistryRefreshService
    dltv_bootstrap: DltvBootstrapCoordinator
    historical_team_resolver: HistoricalTeamResolver
    historical_sync: HistoricalSyncService
    historical_primary: object | None
    historical_repository: HistoricalRepository
    historical_features: HistoricalFeatureBuilder
    opendota: OpenDotaClient
    rosh: RoshService | None
    temporal: TemporalAligner
    snapshot_builder: SnapshotBuilder
    snapshots: SnapshotRepository
    ai: AiCoordinator
    email_notifications: DecisionEmailNotificationService | None
    future_odds: FutureOddsService
    settlement: SettlementService
    evaluation: EvaluationService


class ApplicationJobHandlers:
    def __init__(self, dependencies: JobHandlerDependencies) -> None:
        self._d = dependencies

    def mapping(self):
        return {
            JobType.REFRESH_ODDS_REGISTRY: self.refresh_odds_registry,
            JobType.BOOTSTRAP_DLTV_MATCH: self.bootstrap_dltv_match,
            JobType.SYNC_HISTORICAL: self.sync_historical,
            JobType.BUILD_DRAFT_CURVE: self.build_draft_curve,
            JobType.BUILD_SNAPSHOT: self.build_snapshot,
            JobType.RUN_AI_PROVIDER: self.run_ai,
            JobType.SEND_DECISION_EMAIL: self.send_decision_email,
            JobType.CAPTURE_FUTURE_ODDS: self.capture_future_odds,
            JobType.RESOLVE_POSTMATCH: self.resolve_postmatch,
            JobType.SETTLE_MAP: self.settle_map,
            JobType.EVALUATE_DECISION: self.evaluate_decision,
        }

    async def refresh_odds_registry(self, job: DurableJob) -> None:
        provider_match_id = _required_int(job.payload, "provider_match_id")
        async with self._d.session_factory() as session, session.begin():
            await self._d.registry_refresh.refresh(session, provider_match_id)
            await self._d.health.dependency("RAYBET_HTTP", "READY")
            mapping = await session.scalar(
                select(ProviderMatchMapping).where(
                    ProviderMatchMapping.provider == "raybet",
                    ProviderMatchMapping.provider_match_id == str(provider_match_id),
                )
            )
            if mapping is not None:
                await self._snapshot_event(
                    session,
                    canonical_map_id=mapping.canonical_map_id,
                    canonical_series_id=mapping.canonical_series_id,
                    reason="MARKET_BOOTSTRAP",
                )

    async def bootstrap_dltv_match(self, job: DurableJob) -> None:
        valve_match_id = _required_int(job.payload, "valve_match_id")
        series_id = _optional_int(job.payload.get("dltv_series_id"))
        async with self._d.session_factory() as session, session.begin():
            result = await self._d.dltv_bootstrap.bootstrap(
                session,
                valve_match_id=valve_match_id,
                dltv_series_id=series_id,
            )
            await self._d.health.dependency(
                "DLTV_DRAFT",
                "READY" if result.draft.complete else "DEGRADED",
                message=None if result.draft.complete else "DLTV draft is not complete yet",
                canonical_map_id=str(result.resolved.canonical_map_id),
                valve_match_id=valve_match_id,
                roster_ready_count=sum(slot.account_id is not None for slot in result.draft.slots),
                hero_ready_count=sum(slot.hero_id is not None for slot in result.draft.slots),
                blockers=list(result.draft.blockers),
            )

    async def sync_historical(self, job: DurableJob) -> None:
        async with self._d.session_factory() as session, session.begin():
            canonical_map, series = await self._identity_from_payload(session, job.payload)
            team_ids = [series.team_a_id, series.team_b_id]
            unresolved = []
            for team_id in team_ids:
                mapping = await session.scalar(
                    select(ProviderTeamMapping.id).where(
                        ProviderTeamMapping.provider == "opendota",
                        ProviderTeamMapping.canonical_team_id == team_id,
                    )
                )
                if mapping is None:
                    unresolved.append(team_id)
            if unresolved:
                await self._d.historical_team_resolver.refresh_opendota_catalog(
                    session,
                    self._d.opendota,
                    canonical_team_ids=unresolved,
                )
            if self._d.historical_primary is not None:
                await self._d.historical_team_resolver.refresh_stratz_identities(
                    session,
                    self._d.historical_primary,
                    canonical_team_ids=team_ids,
                )
            cutoff = datetime.now(UTC)
            sync_results = []
            sync_errors = []
            for team_id in team_ids:
                try:
                    async with session.begin_nested():
                        sync_results.append(
                            await self._d.historical_sync.sync_team(
                                session,
                                canonical_team_id=team_id,
                                before=cutoff,
                                limit=self._d.settings.historical_prewarm_maps,
                            )
                        )
                except Exception as exc:
                    sync_errors.append(f"{type(exc).__name__}: {exc}")
            if not sync_results:
                message = "; ".join(sync_errors) or "historical sync produced no team result"
                await self._d.health.dependency("HISTORY", "DEGRADED", message=message)
                await self._d.health.dependency("STRATZ", "DEGRADED", message=message)
                return
            coverage = {
                field: sum(getattr(item, field) for item in sync_results)
                for field in (
                    "maps_requested",
                    "maps_fetched",
                    "maps_normalized",
                    "maps_canonicalized",
                    "maps_eligible_team_rating",
                    "maps_eligible_player_form",
                    "maps_advanced_ready",
                    "identity_missing_count",
                    "provider_fallback_count",
                    "conflict_count",
                )
            }
            await self._d.health.dependency(
                "HISTORY",
                "DEGRADED" if sync_errors else "READY",
                message="; ".join(sync_errors) if sync_errors else None,
                **coverage,
            )
            if self._d.settings.stratz_token:
                fallback_count = coverage["provider_fallback_count"]
                identity_missing = coverage["identity_missing_count"]
                await self._d.health.dependency(
                    "STRATZ",
                    "DEGRADED" if fallback_count or sync_errors else "READY",
                    message="; ".join(sync_errors) if sync_errors else None,
                    provider_fallback_count=fallback_count,
                    identity_missing_count=identity_missing,
                    maps_fetched=coverage["maps_fetched"],
                    maps_normalized=coverage["maps_normalized"],
                )
            await self._d.historical_features.build_team_ratings(session, as_of=cutoff)
            await self._d.historical_features.build_role_baselines(session, as_of=cutoff)
            roster_by_team = {series.team_a_id: [], series.team_b_id: []}
            slots: list[DraftSlotRecord] = []
            if canonical_map is not None:
                draft = await session.scalar(
                    select(DraftSnapshotRecord)
                    .where(
                        DraftSnapshotRecord.canonical_map_id == canonical_map.id,
                        DraftSnapshotRecord.complete.is_(True),
                    )
                    .order_by(DraftSnapshotRecord.observed_at.desc())
                    .limit(1)
                )
                if draft is not None:
                    slots = list(
                        (
                            await session.scalars(
                                select(DraftSlotRecord).where(
                                    DraftSlotRecord.draft_snapshot_id == draft.id
                                )
                            )
                        ).all()
                    )
                    for slot in slots:
                        if slot.canonical_player_id is not None:
                            team_id = (
                                series.team_a_id if slot.side == "radiant" else series.team_b_id
                            )
                            roster_by_team[team_id].append(slot.canonical_player_id)
            for team_id in team_ids:
                await self._d.historical_features.build_team_form(
                    session,
                    canonical_team_id=team_id,
                    roster_player_ids=roster_by_team[team_id],
                    as_of=cutoff,
                )
            for slot in slots:
                if slot.canonical_player_id is None:
                    continue
                await self._d.historical_features.build_player_form(
                    session,
                    canonical_player_id=slot.canonical_player_id,
                    position=slot.position,
                    as_of=cutoff,
                )
                if slot.hero_id is None:
                    continue
                await self._d.historical_features.build_player_hero(
                    session,
                    canonical_player_id=slot.canonical_player_id,
                    hero_id=slot.hero_id,
                    position=slot.position,
                    as_of=cutoff,
                )
            await self._snapshot_event(
                session,
                canonical_map_id=canonical_map.id if canonical_map is not None else None,
                canonical_series_id=series.id,
                reason="HISTORICAL_REFRESH",
            )

    async def build_draft_curve(self, job: DurableJob) -> None:
        if self._d.rosh is None:
            raise RuntimeError("STRATZ_TOKEN is required for Draft Intelligence")
        canonical_map_id = _required_uuid(job.payload, "canonical_map_id")
        draft_snapshot_id = _required_uuid(job.payload, "draft_snapshot_id")
        async with self._d.session_factory() as session, session.begin():
            await self._d.rosh.build(
                session,
                canonical_map_id=canonical_map_id,
                draft_snapshot_id=draft_snapshot_id,
            )
            await self._d.health.dependency("DRAFT_ENGINE", "READY")
            await self._snapshot_event(
                session,
                canonical_map_id=canonical_map_id,
                canonical_series_id=None,
                reason="DRAFT_CURVE_READY",
            )

    async def build_snapshot(self, job: DurableJob) -> None:
        async with self._d.session_factory() as session, session.begin():
            canonical_map, series = await self._identity_from_payload(session, job.payload)
            decision_at = _datetime(job.payload.get("decision_at")) or datetime.now(UTC)
            if canonical_map is not None:
                estimate = await self._d.temporal.calculate(
                    session,
                    canonical_map_id=canonical_map.id,
                    as_of=decision_at,
                )
                await self._d.health.dependency(
                    "LIVE_SYNC",
                    estimate.status,
                    p50_seconds=estimate.p50_seconds,
                    p90_seconds=estimate.p90_seconds,
                    jitter_seconds=estimate.jitter_seconds,
                    sample_size=estimate.sample_size,
                )
            outcome = await self._d.snapshot_builder.build(
                session,
                canonical_map_id=canonical_map.id if canonical_map is not None else None,
                canonical_series_id=series.id,
                decision_at=decision_at,
            )
            if outcome.snapshot is None:
                return
            await self._d.future_odds.schedule(
                session,
                snapshot_id=outcome.snapshot.snapshot_id,
                decision_at=outcome.snapshot.decision_at,
                horizons_seconds=self._d.settings.future_odds_horizons,
            )
            if ai_decision_is_game_time_eligible(
                outcome.snapshot,
                min_game_time_seconds=self._d.settings.ai_min_game_time_seconds,
            ):
                await self._d.events.record(
                    session,
                    DomainEvent(
                        event_type=DomainEventType.AI_DECISION_REQUESTED,
                        aggregate_type="decision_snapshot",
                        aggregate_id=str(outcome.snapshot.snapshot_id),
                        dedupe_key=f"ai:{outcome.snapshot.snapshot_hash}",
                        payload={"snapshot_id": str(outcome.snapshot.snapshot_id)},
                        occurred_at=datetime.now(UTC),
                    ),
                )

    async def run_ai(self, job: DurableJob) -> None:
        snapshot_id = _required_uuid(job.payload, "snapshot_id")
        async with self._d.session_factory() as session, session.begin():
            snapshot = await self._d.snapshots.get(session, snapshot_id)
            if snapshot is None:
                raise ValueError("decision snapshot does not exist")
            if not ai_decision_is_game_time_eligible(
                snapshot,
                min_game_time_seconds=self._d.settings.ai_min_game_time_seconds,
            ):
                return
            existing_ids = set(
                (
                    await session.scalars(
                        select(AiDecisionRecord.id).where(
                            AiDecisionRecord.snapshot_id == snapshot_id
                        )
                    )
                ).all()
            )
            records = await self._d.ai.run_all(session, snapshot)
            dependency_names = {
                "openai": "GPT",
                "anthropic": "CLAUDE",
                "gemini": "GEMINI",
                "deepseek": "DEEPSEEK",
                "kimi": "KIMI",
            }
            records_by_dependency: dict[str, list] = {}
            for record in records:
                dependency = dependency_names.get(record.provider, record.provider.upper())
                records_by_dependency.setdefault(dependency, []).append(record)
            for dependency, dependency_records in records_by_dependency.items():
                failed = [
                    record for record in dependency_records if record.parse_status != "SUCCESS"
                ]
                await self._d.health.dependency(
                    dependency,
                    "DEGRADED" if failed else "READY",
                    message="; ".join(
                        f"{record.model}: {record.error or record.parse_status}"
                        for record in failed
                    )
                    or None,
                    models={
                        record.model: {
                            "parse_status": record.parse_status,
                            "latency_seconds": record.latency_seconds,
                        }
                        for record in dependency_records
                    },
                )
            if self._d.email_notifications is not None and any(
                record.id not in existing_ids for record in records
            ):
                await self._d.email_notifications.prepare(
                    session,
                    snapshot=snapshot,
                    decisions=records,
                )

    async def send_decision_email(self, job: DurableJob) -> None:
        if self._d.email_notifications is None:
            raise RuntimeError("decision email notifications are not configured")
        notification_id = _required_uuid(job.payload, "notification_id")
        try:
            notification = await self._d.email_notifications.deliver(notification_id)
        except Exception as exc:
            await self._d.health.dependency(
                "EMAIL",
                "DEGRADED",
                message=f"{type(exc).__name__}: {exc}",
                notification_id=str(notification_id),
            )
            raise
        await self._d.health.dependency(
            "EMAIL",
            "READY",
            notification_id=str(notification.id),
            recipient_count=len(notification.recipients),
            sent_at=notification.sent_at,
        )

    async def capture_future_odds(self, job: DurableJob) -> None:
        snapshot_id = _required_uuid(job.payload, "snapshot_id")
        capture_type = _required_str(job.payload, "capture_type")
        async with self._d.session_factory() as session, session.begin():
            if capture_type == "TIME_HORIZON":
                await self._d.future_odds.capture(
                    session,
                    snapshot_id=snapshot_id,
                    horizon_seconds=_required_int(job.payload, "horizon_seconds"),
                    due_at=_required_datetime(job.payload, "due_at"),
                    observed_at=datetime.now(UTC),
                )
            elif capture_type == "CLOSING":
                await self._d.future_odds.capture_closing(
                    session,
                    snapshot_id=snapshot_id,
                    triggered_at=_required_datetime(job.payload, "triggered_at"),
                )
            else:
                raise ValueError(f"unsupported future odds capture type: {capture_type}")

    async def resolve_postmatch(self, job: DurableJob) -> None:
        canonical_map_id = _required_uuid(job.payload, "canonical_map_id")
        async with self._d.session_factory() as session:
            canonical_map = await session.get(CanonicalMap, canonical_map_id)
            if canonical_map is None or canonical_map.valve_match_id is None:
                raise ValueError("postmatch map has no Valve Match ID")
            series = await session.get(CanonicalSeries, canonical_map.series_id)
            if series is None:
                raise ValueError("postmatch map has no canonical series")
            valve_match_id = canonical_map.valve_match_id
            expected_team_ids = {series.team_a_id, series.team_b_id}
        provider, response, bundle, raw_event_id = await self._postmatch_response(
            valve_match_id,
            expected_team_ids=expected_team_ids,
        )
        async with self._d.session_factory() as session, session.begin():
            canonical_map = await session.get(CanonicalMap, canonical_map_id)
            if canonical_map is None or canonical_map.valve_match_id != valve_match_id:
                raise ValueError("postmatch map identity changed during resolution")
            fact = await self._d.historical_repository.persist_bundle(
                session,
                bundle,
                raw_event_id=raw_event_id,
                normalizer_version=provider.normalizer_version,
            )
            if fact.winner_team_id is None:
                raise ValueError("postmatch winner identity is not available yet")
            result = await self._d.settlement.settle(
                session,
                canonical_map_id=canonical_map_id,
                winner_team_id=fact.winner_team_id,
                provider=provider.name,
                provider_match_id=bundle.match.provider_match_id,
                result_observed_at=response.received_at,
                basic_first_usable_at=bundle.match.first_usable_at,
                raw_event_id=raw_event_id,
                normalizer_version=provider.normalizer_version,
                identity_confidence=1.0,
                advanced_first_usable_at=(
                    bundle.match.first_usable_at if bundle.advanced_available else None
                ),
                provider_conflict=fact.sync_status == "DATA_CONFLICT",
            )
            await self._d.events.record(
                session,
                DomainEvent(
                    event_type=DomainEventType.BASIC_RESULT_READY,
                    aggregate_type="canonical_map",
                    aggregate_id=str(canonical_map_id),
                    dedupe_key=f"basic-result:{canonical_map_id}",
                    payload={"canonical_map_id": str(canonical_map_id)},
                    occurred_at=result.basic_first_usable_at,
                ),
            )
            if bundle.advanced_available:
                await self._d.events.record(
                    session,
                    DomainEvent(
                        event_type=DomainEventType.ADVANCED_RESULT_READY,
                        aggregate_type="canonical_map",
                        aggregate_id=str(canonical_map_id),
                        dedupe_key=f"advanced-result:{canonical_map_id}",
                        payload={"canonical_map_id": str(canonical_map_id)},
                        occurred_at=bundle.match.first_usable_at,
                    ),
                )

    async def _postmatch_response(self, valve_match_id: int, *, expected_team_ids: set[UUID]):
        failures: list[str] = []
        providers = tuple(
            provider
            for provider in (self._d.historical_primary, self._d.opendota)
            if provider is not None
        )
        for provider in providers:
            try:
                response = await provider.get_match_advanced(valve_match_id)
                if not isinstance(response.payload, dict) or response.payload.get("errors"):
                    raise ValueError("postmatch response is invalid")
                async with self._d.session_factory() as session, session.begin():
                    raw_event_id = await self._d.raw_events.append(
                        session,
                        provider=provider.name,
                        event_type=f"{provider.name.upper()}_POSTMATCH",
                        provider_key=str(valve_match_id),
                        payload=response.payload,
                        request_started_at=response.request_started_at,
                        received_at=response.received_at,
                        parser_version=provider.normalizer_version,
                    )
                bundle = provider.normalize_match(
                    response.payload,
                    fetched_at=response.received_at,
                )
                if bundle.match.winner_team_id is None:
                    raise ValueError("winner is not published")
                provider_team_ids = {
                    bundle.match.radiant_team_id,
                    bundle.match.dire_team_id,
                }
                if None in provider_team_ids:
                    raise ValueError("postmatch team identity is incomplete")
                async with self._d.session_factory() as session, session.begin():
                    await self._d.historical_team_resolver.resolve_observed_match_teams(
                        session,
                        provider=provider.name,
                        observed_teams=_observed_postmatch_teams(provider.name, response.payload),
                        expected_team_ids=expected_team_ids,
                    )
                    canonical_team_ids = set(
                        (
                            await session.scalars(
                                select(ProviderTeamMapping.canonical_team_id).where(
                                    ProviderTeamMapping.provider == provider.name,
                                    ProviderTeamMapping.provider_team_id.in_(provider_team_ids),
                                )
                            )
                        ).all()
                    )
                if canonical_team_ids != expected_team_ids:
                    raise ValueError("postmatch team identity is not canonicalized")
                return provider, response, bundle, raw_event_id
            except Exception as exc:
                failures.append(f"{provider.name}={type(exc).__name__}: {exc}")
        raise RuntimeError(
            f"postmatch result unavailable for Valve match {valve_match_id}: " + "; ".join(failures)
        )

    async def settle_map(self, job: DurableJob) -> None:
        canonical_map_id = _required_uuid(job.payload, "canonical_map_id")
        async with self._d.session_factory() as session, session.begin():
            result = await session.scalar(
                select(MapResultRecord).where(MapResultRecord.canonical_map_id == canonical_map_id)
            )
            if result is None:
                fact = await session.scalar(
                    select(HistoricalMapRecord)
                    .where(
                        HistoricalMapRecord.canonical_map_id == canonical_map_id,
                        HistoricalMapRecord.winner_team_id.is_not(None),
                    )
                    .order_by(HistoricalMapRecord.first_usable_at)
                    .limit(1)
                )
                if fact is None:
                    raise ValueError("map result is not available")
                result = await self._d.settlement.settle(
                    session,
                    canonical_map_id=canonical_map_id,
                    winner_team_id=fact.winner_team_id,
                    provider=fact.provider,
                    provider_match_id=fact.provider_match_id,
                    result_observed_at=fact.fetched_at or fact.first_usable_at,
                    basic_first_usable_at=fact.first_usable_at,
                    raw_event_id=fact.raw_event_id,
                    normalizer_version=fact.normalizer_version or "unknown",
                    identity_confidence=1.0,
                    advanced_first_usable_at=fact.advanced_ready_at,
                    provider_conflict=fact.sync_status == "DATA_CONFLICT",
                )
            snapshots = list(
                (
                    await session.scalars(
                        select(DecisionSnapshotRecord.id).where(
                            DecisionSnapshotRecord.canonical_map_id == canonical_map_id
                        )
                    )
                ).all()
            )
            for snapshot_id in snapshots:
                await self._d.events.record(
                    session,
                    DomainEvent(
                        event_type=DomainEventType.EVALUATION_REQUIRED,
                        aggregate_type="decision_snapshot",
                        aggregate_id=str(snapshot_id),
                        dedupe_key=f"evaluation:{snapshot_id}",
                        payload={"snapshot_id": str(snapshot_id)},
                        occurred_at=datetime.now(UTC),
                    ),
                )

    async def evaluate_decision(self, job: DurableJob) -> None:
        snapshot_id = _required_uuid(job.payload, "snapshot_id")
        async with self._d.session_factory() as session, session.begin():
            await self._d.evaluation.evaluate_snapshot(session, snapshot_id=snapshot_id)

    async def _snapshot_event(
        self,
        session: AsyncSession,
        *,
        canonical_map_id: UUID | None,
        canonical_series_id: UUID | None,
        reason: str,
    ) -> None:
        now = datetime.now(UTC)
        aggregate_id = str(canonical_map_id or canonical_series_id)
        await self._d.events.record(
            session,
            DomainEvent(
                event_type=DomainEventType.SNAPSHOT_BUILD_REQUESTED,
                aggregate_type=(
                    "canonical_map" if canonical_map_id is not None else "canonical_series"
                ),
                aggregate_id=aggregate_id,
                dedupe_key=f"snapshot:{aggregate_id}:{reason}:{now.isoformat()}",
                payload={
                    "canonical_map_id": (
                        str(canonical_map_id) if canonical_map_id is not None else None
                    ),
                    "canonical_series_id": (
                        str(canonical_series_id) if canonical_series_id is not None else None
                    ),
                    "decision_at": now.isoformat(),
                    "reason": reason,
                },
                occurred_at=now,
            ),
        )

    async def _identity_from_payload(
        self, session: AsyncSession, payload: dict
    ) -> tuple[CanonicalMap | None, CanonicalSeries]:
        canonical_map_id = _optional_uuid(payload.get("canonical_map_id"))
        canonical_series_id = _optional_uuid(payload.get("canonical_series_id"))
        provider_match_id = _optional_int(payload.get("provider_match_id"))
        if canonical_map_id is None and canonical_series_id is None and provider_match_id:
            mapping = await session.scalar(
                select(ProviderMatchMapping).where(
                    ProviderMatchMapping.provider == "raybet",
                    ProviderMatchMapping.provider_match_id == str(provider_match_id),
                )
            )
            if mapping is not None:
                canonical_map_id = mapping.canonical_map_id
                canonical_series_id = mapping.canonical_series_id
        canonical_map = (
            await session.get(CanonicalMap, canonical_map_id)
            if canonical_map_id is not None
            else None
        )
        series_id = canonical_map.series_id if canonical_map is not None else canonical_series_id
        series = await session.get(CanonicalSeries, series_id)
        if series is None:
            raise ValueError("job payload cannot be resolved to a canonical series")
        return canonical_map, series


def _required_int(payload: dict, key: str) -> int:
    value = _optional_int(payload.get(key))
    if value is None:
        raise ValueError(f"job payload field {key} must be an integer")
    return value


def _observed_postmatch_teams(
    provider: str,
    payload: dict,
) -> tuple[tuple[str, str | None], ...]:
    if provider == "opendota":
        pairs = (
            (payload.get("radiant_team_id"), payload.get("radiant_name")),
            (payload.get("dire_team_id"), payload.get("dire_name")),
        )
    elif provider == "stratz":
        match = payload.get("data", {}).get("match")
        if not isinstance(match, dict):
            return ()
        radiant = match.get("radiantTeam") if isinstance(match.get("radiantTeam"), dict) else {}
        dire = match.get("direTeam") if isinstance(match.get("direTeam"), dict) else {}
        pairs = (
            (match.get("radiantTeamId"), radiant.get("name")),
            (match.get("direTeamId"), dire.get("name")),
        )
    else:
        return ()
    return tuple(
        (str(team_id), name if isinstance(name, str) and name.strip() else None)
        for team_id, name in pairs
        if isinstance(team_id, int)
    )


def _required_str(payload: dict, key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"job payload field {key} must be a non-empty string")
    return value


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _required_uuid(payload: dict, key: str) -> UUID:
    value = _optional_uuid(payload.get(key))
    if value is None:
        raise ValueError(f"job payload field {key} must be a UUID")
    return value


def _optional_uuid(value: object) -> UUID | None:
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        try:
            return UUID(value)
        except ValueError:
            return None
    return None


def _datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return ensure_utc(value)
    if isinstance(value, str):
        try:
            return ensure_utc(datetime.fromisoformat(value))
        except ValueError:
            return None
    return None


def _required_datetime(payload: dict, key: str) -> datetime:
    value = _datetime(payload.get(key))
    if value is None:
        raise ValueError(f"job payload field {key} must be an ISO datetime")
    return value
