import asyncio
import os
import signal
import socket
from datetime import UTC, datetime, timedelta
from pathlib import Path

import structlog
from alembic import command
from alembic.config import Config as AlembicConfig
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import func, select, text

from app.ai import (
    AiCoordinator,
    AnthropicDecisionProvider,
    DeepSeekDecisionProvider,
    GeminiDecisionProvider,
    KimiDecisionProvider,
    OpenAiDecisionProvider,
)
from app.ai.base import ai_experiment_key
from app.config import Settings, get_settings
from app.db import create_engine, create_session_factory
from app.db_partitions import ensure_weekly_partitions
from app.domain.jobs import JobType
from app.draft.coordinator import DltvBootstrapCoordinator
from app.draft.refresh import schedule_incomplete_draft_refreshes
from app.draft.role_assignment import DraftRoleAssignmentService
from app.draft.rosh_service import RoshService
from app.evaluation import EvaluationService, FutureOddsService, SettlementService
from app.events.dispatcher import DomainEventDispatcher, OutboxDispatcher
from app.events.hub import EventHub
from app.events.outbox import EventRepository
from app.history.builder import HistoricalFeatureBuilder
from app.history.identity import HistoricalTeamResolver
from app.history.repository import HistoricalRepository
from app.history.service import HistoricalIntelligenceService
from app.history.sync import HistoricalSyncService
from app.identity.resolver import IdentityResolver
from app.jobs.handlers import ApplicationJobHandlers, JobHandlerDependencies
from app.jobs.reconciliation import ReconciliationService
from app.jobs.repository import JobRepository
from app.jobs.runner import JobRunner
from app.live.collector import DltvSocketCollector
from app.market.collector import RayBetOddsCollector
from app.market.discovery import RayBetDiscoveryService
from app.market.odds_registry import OddsRegistry
from app.market.registry_refresh import RayBetRegistryRefreshService
from app.models import (
    CanonicalSeries,
    DecisionEmailNotificationRecord,
    DltvLiveObservationRecord,
    HistoricalMapRecord,
    HistoricalPlayerMapRecord,
    LiveSyncEstimateRecord,
    ProviderMatchMapping,
)
from app.notifications import DecisionEmailNotificationService, ResendEmailSender
from app.notifications.translation import DeepSeekEmailTranslator
from app.observability import Metrics, configure_logging, configure_tracing
from app.providers.dltv.bootstrap import DltvBootstrapClient
from app.providers.dltv.socket import DltvSocketClient
from app.providers.opendota.client import OpenDotaClient
from app.providers.raybet.http import RayBetHttpClient, RayBetHttpPool
from app.providers.raybet.http_transport import CurlRayBetHttpClient, CurlRayBetHttpPool
from app.providers.raybet.socket import RayBetSocketClient
from app.providers.stratz.client import StratzClient
from app.providers.stratz.history import StratzHistoricalProvider
from app.repositories.raw import RawEventRepository
from app.runtime.health import HealthRegistry
from app.runtime.supervisor import Supervisor
from app.runtime.worker import PeriodicWorker, ServiceWorker
from app.snapshots.builder import SnapshotBuilder
from app.snapshots.repository import SnapshotRepository
from app.temporal.aligner import TemporalAligner
from app.web import WebServerWorker, create_app

logger = structlog.get_logger()
ROOT = Path(__file__).resolve().parents[1]


async def run() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    configure_tracing(settings.otel_exporter_otlp_endpoint)
    _assert_bind_safety(settings)
    if settings.auto_migrate:
        await asyncio.to_thread(_upgrade_database)

    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    health = HealthRegistry()
    metrics = Metrics()
    await _validate_database(engine, health)
    await ensure_weekly_partitions(engine)

    raw_events = RawEventRepository()
    events = EventRepository()
    jobs = JobRepository()
    identities = IdentityResolver()
    odds_registry = OddsRegistry()
    raybet_http = RayBetHttpPool(
        tuple(RayBetHttpClient(host, settings.raybet_origin) for host in settings.raybet_http_hosts)
    )
    raybet_curl = CurlRayBetHttpPool(
        tuple(
            CurlRayBetHttpClient(host, settings.raybet_origin)
            for host in settings.raybet_http_hosts
        )
    )
    raybet_socket = RayBetSocketClient(settings.raybet_socket_url, settings.raybet_origin)
    dltv_http = DltvBootstrapClient(settings.dltv_base_url)
    dltv_socket = DltvSocketClient(settings.dltv_base_url)
    opendota = OpenDotaClient(
        settings.opendota_base_url,
        settings.opendota_api_key.get_secret_value() if settings.opendota_api_key else None,
    )
    stratz_client = (
        StratzClient(settings.stratz_graphql_url, settings.stratz_token.get_secret_value())
        if settings.stratz_token
        else None
    )
    stratz_history = StratzHistoricalProvider(stratz_client) if stratz_client is not None else None

    async def observe_match(session, match) -> None:
        await identities.observe_raybet_match(session, match)

    market_collector = RayBetOddsCollector(
        raw_events=raw_events,
        registry=odds_registry,
        events=events,
        significant_move=settings.significant_odds_move,
    )
    registry_refresh = RayBetRegistryRefreshService(
        raybet_http,
        raybet_curl,
        raw_events,
        odds_registry,
        market_collector,
    )
    discovery = RayBetDiscoveryService(
        settings=settings,
        client=raybet_http,
        fallback_client=raybet_curl,
        raw_events=raw_events,
        events=events,
        on_match=observe_match,
    )
    dltv_bootstrap = DltvBootstrapCoordinator(
        client=dltv_http,
        raw_events=raw_events,
        events=events,
        identities=identities,
        role_assignment=DraftRoleAssignmentService(
            stratz=stratz_client,
            raw_events=raw_events,
        ),
    )
    dltv_collector = DltvSocketCollector(
        session_factory=session_factory,
        raw_events=raw_events,
        events=events,
        checkpoint_minutes=settings.checkpoint_minutes,
    )
    historical_repository = HistoricalRepository()
    historical_sync = HistoricalSyncService(
        primary=stratz_history,
        fallback=opendota,
        raw_events=raw_events,
        repository=historical_repository,
        batch_size=settings.historical_sync_batch_maps,
    )
    historical_features = HistoricalFeatureBuilder(
        initial_elo=settings.elo_initial_rating,
        elo_k=settings.elo_k_factor,
    )
    snapshots = SnapshotRepository()
    temporal = TemporalAligner(settings)
    snapshot_builder = SnapshotBuilder(
        settings=settings,
        history=HistoricalIntelligenceService(),
        repository=snapshots,
    )
    ai_providers = _ai_providers(settings)
    ai = AiCoordinator(
        ai_providers,
        timeout_seconds=settings.ai_timeout_seconds,
        max_live_data_lag_seconds=settings.ai_max_live_data_lag_seconds,
    )
    email_notifications = _email_notifications(
        settings,
        session_factory=session_factory,
        jobs=jobs,
    )
    future_odds = FutureOddsService(
        jobs,
        market_max_age_seconds=settings.live_market_max_age_seconds,
        market_max_pair_skew_seconds=settings.market_max_pair_skew_seconds,
    )
    rosh = RoshService(stratz_client, raw_events) if stratz_client is not None else None
    await _initialize_dependency_health(
        health, settings=settings, ai_provider_names=tuple(item.name for item in ai_providers)
    )
    await _restore_historical_health(
        health,
        session_factory=session_factory,
        stratz_configured=bool(settings.stratz_token),
    )
    await _restore_email_health(
        health,
        session_factory=session_factory,
        configured=email_notifications is not None,
    )

    handlers = ApplicationJobHandlers(
        JobHandlerDependencies(
            settings=settings,
            health=health,
            session_factory=session_factory,
            events=events,
            raw_events=raw_events,
            registry_refresh=registry_refresh,
            dltv_bootstrap=dltv_bootstrap,
            historical_team_resolver=HistoricalTeamResolver(raw_events),
            historical_sync=historical_sync,
            historical_primary=stratz_history,
            historical_repository=historical_repository,
            historical_features=historical_features,
            opendota=opendota,
            rosh=rosh,
            temporal=temporal,
            snapshot_builder=snapshot_builder,
            snapshots=snapshots,
            ai=ai,
            email_notifications=email_notifications,
            future_odds=future_odds,
            settlement=SettlementService(),
            evaluation=EvaluationService(),
        )
    ).mapping()
    reconciliation = ReconciliationService(
        jobs,
        lease_seconds=settings.job_lease_seconds,
        ai_experiments=tuple(ai_experiment_key(item.name, item.model) for item in ai_providers),
        future_odds_horizons=settings.future_odds_horizons,
        ai_min_game_time_seconds=settings.ai_min_game_time_seconds,
    )
    async with session_factory() as session, session.begin():
        await reconciliation.run(session, now=datetime.now(UTC))

    hub = EventHub()
    domain_dispatcher = DomainEventDispatcher(jobs)
    outbox_dispatcher = OutboxDispatcher(session_factory, hub.publish)
    workers = []

    async def dispatch_events() -> None:
        async with session_factory() as session, session.begin():
            await domain_dispatcher.dispatch_pending(session)

    async def reconcile() -> None:
        async with session_factory() as session, session.begin():
            result = await reconciliation.run(session, now=datetime.now(UTC))
            counts = await jobs.counts_by_status(session)
            for status, count in counts.items():
                metrics.jobs.labels(status=status).set(count)
            logger.info("reconciliation_completed", **result.__dict__)

    async def discover() -> None:
        async with session_factory() as session, session.begin():
            count = await discovery.discover_once(session)
        await health.dependency("RAYBET_HTTP", "READY", matches_discovered=count)

    async def maintain_partitions() -> None:
        await ensure_weekly_partitions(engine)

    async def refresh_incomplete_drafts() -> None:
        async with session_factory() as session, session.begin():
            result = await schedule_incomplete_draft_refreshes(
                session,
                jobs,
                interval_seconds=settings.dltv_bootstrap_interval_seconds,
            )
        if result.enqueued:
            await health.dependency(
                "DLTV_DRAFT",
                "DEGRADED",
                message="waiting for a complete DLTV draft",
                active_maps=result.active_maps,
                refreshes_enqueued=result.enqueued,
            )

    async def schedule_historical_refresh() -> None:
        now = datetime.now(UTC)
        async with session_factory() as session, session.begin():
            series_ids = list(
                (
                    await session.scalars(
                        select(CanonicalSeries.id).where(
                            CanonicalSeries.scheduled_at >= now - timedelta(hours=12),
                            CanonicalSeries.scheduled_at <= now + timedelta(days=2),
                            select(ProviderMatchMapping.id)
                            .where(
                                ProviderMatchMapping.provider == "raybet",
                                ProviderMatchMapping.canonical_series_id == CanonicalSeries.id,
                            )
                            .exists(),
                        )
                    )
                ).all()
            )
            bucket = int(now.timestamp() // settings.historical_refresh_seconds)
            for series_id in series_ids:
                await jobs.enqueue(
                    session,
                    job_type=JobType.SYNC_HISTORICAL,
                    dedupe_key=f"periodic-history:{series_id}:{bucket}",
                    payload={"canonical_series_id": str(series_id)},
                )

    async def align_live_maps() -> None:
        now = datetime.now(UTC)
        async with session_factory() as session, session.begin():
            map_ids = set(
                (
                    await session.scalars(
                        select(DltvLiveObservationRecord.canonical_map_id)
                        .where(
                            DltvLiveObservationRecord.canonical_map_id.is_not(None),
                            DltvLiveObservationRecord.received_at >= now - timedelta(minutes=10),
                        )
                        .order_by(DltvLiveObservationRecord.received_at.desc())
                        .limit(32)
                    )
                ).all()
            )
            for map_id in map_ids:
                if map_id is None:
                    continue
                latest_message = await session.scalar(
                    select(func.max(DltvLiveObservationRecord.received_at)).where(
                        DltvLiveObservationRecord.canonical_map_id == map_id
                    )
                )
                latest_estimate = await session.scalar(
                    select(func.max(LiveSyncEstimateRecord.calculated_at)).where(
                        LiveSyncEstimateRecord.canonical_map_id == map_id
                    )
                )
                if latest_estimate is not None and latest_message is not None:
                    if latest_estimate >= latest_message:
                        continue
                estimate = await temporal.calculate(session, canonical_map_id=map_id, as_of=now)
                await health.dependency(
                    "LIVE_SYNC",
                    estimate.status,
                    p50_seconds=estimate.p50_seconds,
                    p90_seconds=estimate.p90_seconds,
                    sample_size=estimate.sample_size,
                )

    workers.extend(
        [
            PeriodicWorker(
                name="DomainEventDispatcher",
                interval_seconds=0.25,
                action=dispatch_events,
                health_registry=health,
            ),
            PeriodicWorker(
                name="OutboxDispatcher",
                interval_seconds=0.5,
                action=outbox_dispatcher.dispatch_once,
                health_registry=health,
            ),
            PeriodicWorker(
                name="ReconciliationWorker",
                interval_seconds=settings.reconciliation_interval_seconds,
                action=reconcile,
                health_registry=health,
            ),
            PeriodicWorker(
                name="PartitionMaintenanceWorker",
                interval_seconds=21_600,
                action=maintain_partitions,
                health_registry=health,
            ),
            PeriodicWorker(
                name="HistoricalRefreshScheduler",
                interval_seconds=settings.historical_refresh_seconds,
                action=schedule_historical_refresh,
                health_registry=health,
            ),
            PeriodicWorker(
                name="DltvDraftRefreshScheduler",
                interval_seconds=settings.dltv_bootstrap_interval_seconds,
                action=refresh_incomplete_drafts,
                health_registry=health,
            ),
            PeriodicWorker(
                name="TemporalAligner",
                interval_seconds=5,
                action=align_live_maps,
                health_registry=health,
            ),
        ]
    )
    workers.extend(
        _job_workers(
            settings=settings,
            session_factory=session_factory,
            jobs=jobs,
            handlers=handlers,
            health=health,
        )
    )

    if settings.run_provider_workers:
        workers.append(
            PeriodicWorker(
                name="RayBetDiscoveryWorker",
                interval_seconds=settings.raybet_discovery_interval_seconds,
                action=discover,
                health_registry=health,
            )
        )

    async def raybet_publish(message: dict) -> None:
        async with session_factory() as session, session.begin():
            count = await market_collector.collect(session, message)
        metrics.provider_messages.labels(provider="raybet", type="socket").inc()
        await health.message("RayBetSocketWorker", observations=count)
        await health.dependency(
            "RAYBET_SOCKET",
            "READY",
            business_message=True,
            requires_message=True,
            max_message_age_seconds=settings.provider_business_message_max_age_seconds,
            observations=count,
        )

    async def raybet_state(state: str, error: str | None) -> None:
        connected = state == "CONNECTED"
        metrics.provider_connected.labels(provider="raybet").set(int(connected))
        await health.dependency(
            "RAYBET_SOCKET",
            "UNKNOWN" if connected else "DEGRADED",
            message=error,
            requires_message=True,
            max_message_age_seconds=settings.provider_business_message_max_age_seconds,
            connected=connected,
        )

    async def dltv_event(
        event_name: str,
        payload: dict,
        connection_id: str,
        reconnect_generation: int,
    ) -> None:
        await dltv_collector.collect(
            event_name,
            payload,
            connection_id,
            reconnect_generation,
        )
        metrics.provider_messages.labels(provider="dltv", type=event_name).inc()
        await health.message("DltvSocketWorker", event_name=event_name)
        await health.dependency(
            "DLTV_SOCKET",
            "READY",
            business_message=True,
            requires_message=True,
            max_message_age_seconds=settings.provider_business_message_max_age_seconds,
            event_name=event_name,
        )

    async def dltv_state(state: str, error: str | None) -> None:
        connected = state == "CONNECTED"
        metrics.provider_connected.labels(provider="dltv").set(int(connected))
        await health.dependency(
            "DLTV_SOCKET",
            "UNKNOWN" if connected else "DEGRADED",
            message=error,
            requires_message=True,
            max_message_age_seconds=settings.provider_business_message_max_age_seconds,
            connected=connected,
        )

    if settings.run_provider_workers:
        workers.extend(
            _provider_socket_workers(
                raybet_socket=raybet_socket,
                dltv_socket=dltv_socket,
                raybet_publish=raybet_publish,
                raybet_state=raybet_state,
                dltv_event=dltv_event,
                dltv_state=dltv_state,
                health=health,
            )
        )

    frontend_dist = ROOT / "frontend" / "dist"
    app = create_app(
        session_factory,
        health,
        frontend_dist=frontend_dist,
        live_state_max_age_seconds=settings.live_state_max_age_seconds,
        live_market_max_age_seconds=settings.live_market_max_age_seconds,
        market_max_pair_skew_seconds=settings.market_max_pair_skew_seconds,
    )
    workers.append(
        WebServerWorker(
            app,
            host=settings.host,
            port=settings.port,
            log_level=settings.log_level,
            health=health,
        )
    )
    supervisor = Supervisor(
        workers,
        health=health,
        max_backoff_seconds=settings.worker_max_backoff_seconds,
    )
    shutdown = asyncio.Event()
    _install_signal_handlers(shutdown)
    supervisor_task = asyncio.create_task(supervisor.run())
    logger.info("runtime_started", host=settings.host, port=settings.port)
    try:
        await shutdown.wait()
    finally:
        await supervisor.stop()
        await supervisor_task
        if email_notifications is not None:
            await email_notifications.close()
        await ai.close()
        await opendota.close()
        if stratz_history is not None:
            await stratz_history.close()
        await dltv_http.close()
        await raybet_http.close()
        await raybet_curl.close()
        await engine.dispose()
        logger.info("runtime_stopped")


def _job_workers(*, settings, session_factory, jobs, handlers, health) -> list[ServiceWorker]:
    groups = {
        "RayBetRegistryRefreshWorker": (JobType.REFRESH_ODDS_REGISTRY,),
        "DltvBootstrapWorker": (JobType.BOOTSTRAP_DLTV_MATCH, JobType.REPAIR_LEGACY_DRAFT),
        "HistoricalSyncWorker": (JobType.SYNC_HISTORICAL,),
        "DraftCoordinator": (JobType.BUILD_DRAFT_CURVE,),
        "SnapshotCoordinator": (JobType.BUILD_SNAPSHOT,),
        "AiCoordinatorWorker": (JobType.RUN_AI_PROVIDER,),
        "FutureOddsWorker": (JobType.CAPTURE_FUTURE_ODDS,),
        "PostmatchResolverWorker": (JobType.RESOLVE_POSTMATCH,),
        "SettlementWorker": (JobType.SETTLE_MAP,),
        "EvaluationWorker": (JobType.EVALUATE_DECISION,),
    }
    if settings.email_notifications_enabled and not settings.email_configuration_errors:
        groups["EmailNotificationWorker"] = (JobType.SEND_DECISION_EMAIL,)
    result = []
    identity = f"{socket.gethostname()}:{os.getpid()}"
    for name, job_types in groups.items():
        runner = JobRunner(
            worker_id=f"{identity}:{name}",
            session_factory=session_factory,
            repository=jobs,
            handlers=handlers,
            poll_seconds=settings.job_poll_seconds,
            lease_seconds=settings.job_lease_seconds,
            job_types=job_types,
        )
        result.append(
            ServiceWorker(
                name=name,
                run=runner.run,
                stop=runner.stop,
                health_registry=health,
            )
        )
    return result


def _provider_socket_workers(
    *,
    raybet_socket,
    dltv_socket,
    raybet_publish,
    raybet_state,
    dltv_event,
    dltv_state,
    health,
) -> list[ServiceWorker]:
    return [
        ServiceWorker(
            name="RayBetSocketWorker",
            run=lambda: raybet_socket.run(raybet_publish, raybet_state),
            stop=raybet_socket.stop,
            health_registry=health,
        ),
        ServiceWorker(
            name="DltvSocketWorker",
            run=lambda: dltv_socket.run(dltv_event, dltv_state),
            stop=dltv_socket.stop,
            health_registry=health,
        ),
    ]


_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def _assert_bind_safety(settings: Settings) -> None:
    """Refuse to expose the unauthenticated API beyond loopback.

    The dashboard has no auth layer (CORS is not a security boundary), so
    binding a non-loopback address without an API token would publish match
    intelligence and decision state to the network.
    """
    if settings.host not in _LOOPBACK_HOSTS and settings.api_token is None:
        raise RuntimeError(
            "refusing to start: HOST is non-loopback but API_TOKEN is not configured"
        )


def _ai_providers(settings: Settings):
    providers = []
    if settings.openai_api_key:
        providers.append(
            OpenAiDecisionProvider(
                api_key=settings.openai_api_key.get_secret_value(),
                model=settings.openai_model,
                base_url=settings.openai_base_url,
                reasoning_effort=settings.openai_reasoning_effort,
                timeout_seconds=settings.ai_timeout_seconds,
            )
        )
    if settings.anthropic_api_key:
        providers.append(
            AnthropicDecisionProvider(
                api_key=settings.anthropic_api_key.get_secret_value(),
                model=settings.anthropic_model,
                base_url=settings.anthropic_base_url,
                timeout_seconds=settings.ai_timeout_seconds,
            )
        )
    if settings.gemini_api_key:
        providers.append(
            GeminiDecisionProvider(
                api_key=settings.gemini_api_key.get_secret_value(),
                model=settings.gemini_model,
                base_url=settings.gemini_base_url,
                timeout_seconds=settings.ai_timeout_seconds,
            )
        )
    if settings.deepseek_api_key:
        if settings.deepseek_flash_decisions_enabled:
            providers.append(
                DeepSeekDecisionProvider(
                    api_key=settings.deepseek_api_key.get_secret_value(),
                    model=settings.deepseek_model,
                    base_url=settings.deepseek_base_url,
                    reasoning_effort=settings.deepseek_reasoning_effort,
                    timeout_seconds=settings.ai_timeout_seconds,
                )
            )
        providers.append(
            DeepSeekDecisionProvider(
                api_key=settings.deepseek_api_key.get_secret_value(),
                model=settings.deepseek_pro_model,
                base_url=settings.deepseek_base_url,
                reasoning_effort=settings.deepseek_reasoning_effort,
                timeout_seconds=settings.ai_timeout_seconds,
            )
        )
    if settings.kimi_api_key:
        providers.append(
            KimiDecisionProvider(
                api_key=settings.kimi_api_key.get_secret_value(),
                model=settings.kimi_model,
                base_url=settings.kimi_base_url,
                timeout_seconds=settings.ai_timeout_seconds,
            )
        )
    return providers


def _email_notifications(settings: Settings, *, session_factory, jobs):
    if not settings.email_notifications_enabled or settings.email_configuration_errors:
        return None
    assert settings.resend_api_key is not None
    assert settings.resend_from is not None
    sender = ResendEmailSender(
        api_key=settings.resend_api_key.get_secret_value(),
        base_url=settings.resend_base_url,
        timeout_seconds=settings.resend_timeout_seconds,
    )
    translator = (
        DeepSeekEmailTranslator(
            api_key=settings.deepseek_api_key.get_secret_value(),
            model=settings.deepseek_model,
            base_url=settings.deepseek_base_url,
            reasoning_effort=settings.deepseek_reasoning_effort,
            timeout_seconds=settings.ai_timeout_seconds,
        )
        if settings.deepseek_api_key
        else None
    )
    return DecisionEmailNotificationService(
        session_factory=session_factory,
        jobs=jobs,
        sender=sender,
        sender_from=settings.resend_from,
        recipients=settings.decision_email_recipients,
        subject_prefix=settings.email_subject_prefix,
        translator=translator,
    )


async def _initialize_dependency_health(
    health: HealthRegistry,
    *,
    settings: Settings,
    ai_provider_names: tuple[str, ...],
) -> None:
    for dependency in ("RAYBET_HTTP", "DLTV_DRAFT"):
        await health.dependency(dependency, "UNKNOWN")
    for dependency in ("RAYBET_SOCKET", "DLTV_SOCKET"):
        await health.dependency(
            dependency,
            "UNKNOWN",
            requires_message=True,
            max_message_age_seconds=settings.provider_business_message_max_age_seconds,
        )
    await health.dependency("LIVE_SYNC", "UNKNOWN")
    await health.dependency("HISTORY", "UNKNOWN")
    if not settings.email_notifications_enabled:
        await health.dependency("EMAIL", "DISABLED")
    elif settings.email_configuration_errors:
        await health.dependency(
            "EMAIL",
            "ACTION_REQUIRED",
            message="missing configuration: " + ", ".join(settings.email_configuration_errors),
        )
    else:
        await health.dependency(
            "EMAIL",
            "UNKNOWN",
            recipient_count=len(settings.decision_email_recipients),
        )
    await health.dependency("STRATZ", "UNKNOWN" if settings.stratz_token else "ACTION_REQUIRED")
    await health.dependency(
        "DRAFT_ENGINE", "UNKNOWN" if settings.stratz_token else "ACTION_REQUIRED"
    )
    provider_dependencies = {
        "openai": "GPT",
        "anthropic": "CLAUDE",
        "gemini": "GEMINI",
        "deepseek": "DEEPSEEK",
        "kimi": "KIMI",
    }
    for provider, dependency in provider_dependencies.items():
        await health.dependency(
            dependency,
            "UNKNOWN" if provider in ai_provider_names else "ACTION_REQUIRED",
        )


async def _restore_historical_health(
    health: HealthRegistry,
    *,
    session_factory,
    stratz_configured: bool,
) -> None:
    async with session_factory() as session:
        map_count = await session.scalar(select(func.count()).select_from(HistoricalMapRecord)) or 0
        player_map_count = (
            await session.scalar(select(func.count()).select_from(HistoricalPlayerMapRecord)) or 0
        )
        latest_history = await session.scalar(select(func.max(HistoricalMapRecord.fetched_at)))
        stratz_map_count = (
            await session.scalar(
                select(func.count())
                .select_from(HistoricalMapRecord)
                .where(HistoricalMapRecord.provider == "stratz")
            )
            or 0
        )
        latest_stratz = await session.scalar(
            select(func.max(HistoricalMapRecord.fetched_at)).where(
                HistoricalMapRecord.provider == "stratz"
            )
        )
    if map_count and latest_history is not None:
        await health.restore_dependency(
            "HISTORY",
            "READY",
            last_success_at=latest_history,
            maps_stored=map_count,
            player_maps_stored=player_map_count,
        )
    if stratz_configured and stratz_map_count and latest_stratz is not None:
        await health.restore_dependency(
            "STRATZ",
            "DEGRADED",
            last_success_at=latest_stratz,
            message="local STRATZ facts restored; live provider not verified since restart",
            maps_stored=stratz_map_count,
        )


async def _restore_email_health(health, *, session_factory, configured: bool) -> None:
    if not configured:
        return
    async with session_factory() as session:
        latest = await session.scalar(
            select(DecisionEmailNotificationRecord)
            .order_by(DecisionEmailNotificationRecord.created_at.desc())
            .limit(1)
        )
    if latest is None:
        return
    if latest.status == "SENT" and latest.sent_at is not None:
        await health.restore_dependency(
            "EMAIL",
            "READY",
            last_success_at=latest.sent_at,
            recipient_count=len(latest.recipients),
            notification_id=str(latest.id),
        )
    elif latest.status == "FAILED":
        await health.dependency(
            "EMAIL",
            "DEGRADED",
            message=latest.last_error,
            notification_id=str(latest.id),
        )


async def _validate_database(engine, health: HealthRegistry) -> None:
    try:
        async with engine.connect() as connection:
            await connection.execute(text("select 1"))
            current = await connection.run_sync(
                lambda sync_connection: MigrationContext.configure(
                    sync_connection
                ).get_current_revision()
            )
        config = AlembicConfig(str(ROOT / "alembic.ini"))
        head = ScriptDirectory.from_config(config).get_current_head()
        if current != head:
            raise RuntimeError(f"database revision {current} is not migration head {head}")
    except Exception as exc:
        await health.dependency(
            "DATABASE", "ACTION_REQUIRED", message=f"{type(exc).__name__}: {exc}"
        )
        raise
    await health.dependency("DATABASE", "READY", revision=current)


def _upgrade_database() -> None:
    config = AlembicConfig(str(ROOT / "alembic.ini"))
    command.upgrade(config, "head")


def _install_signal_handlers(shutdown: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()

    def request_shutdown(*_args) -> None:
        loop.call_soon_threadsafe(shutdown.set)

    signal.signal(signal.SIGINT, request_shutdown)
    signal.signal(signal.SIGTERM, request_shutdown)


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
