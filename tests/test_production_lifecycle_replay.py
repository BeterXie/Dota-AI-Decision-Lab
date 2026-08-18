import asyncio
import json
import os
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.ai.base import AiProviderResponse
from app.ai.coordinator import AiCoordinator
from app.config import Settings, get_settings
from app.domain.decision import AiDecision
from app.domain.jobs import JobType
from app.draft.coordinator import DltvBootstrapCoordinator
from app.draft.engine import score_rosh_lineups
from app.draft.features import build_draft_curve
from app.draft.role_assignment import DraftRoleAssignmentService
from app.evaluation import EvaluationService, FutureOddsService, SettlementService
from app.events.outbox import EventRepository
from app.history.repository import HistoricalRepository
from app.history.service import HistoricalIntelligenceService
from app.history.sync import HistoricalSyncService
from app.identity.resolver import IdentityResolver
from app.jobs.repository import JobRepository
from app.live.collector import DltvSocketCollector
from app.market.collector import RayBetOddsCollector
from app.market.odds_registry import OddsRegistry
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
    OddsObservationRecord,
    ProviderMatchMapping,
    ProviderRawEvent,
    ProviderTeamMapping,
    RayBetOddsRegistry,
)
from app.providers.common import TimedPayload
from app.providers.opendota.normalizer import normalize_match as normalize_opendota_match
from app.repositories.raw import RawEventRepository
from app.snapshots.builder import SnapshotBuilder
from app.snapshots.repository import SnapshotRepository
from app.temporal.aligner import TemporalAligner

FIXTURES = Path(__file__).parent / "fixtures"
ROOT = Path(__file__).resolve().parents[1]
VALVE_MATCH_ID = 8940730389
RAYBET_MATCH_ID = 38423651
HISTORICAL_MATCH_ID = VALVE_MATCH_ID - 1


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _analysis() -> dict:
    meta: dict[str, list[dict]] = {"heroes": []}
    by_time: dict[str, list[dict]] = {}
    for position in range(1, 6):
        radiant = position
        dire = 100 + position
        meta[f"heroesPos_{position}"] = [
            {"heroId": radiant, "matchCount": 1000, "winCount": 550},
            {"heroId": dire, "matchCount": 1000, "winCount": 450},
        ]
        rows: list[dict] = []
        for minute in range(20, 61):
            rows.extend(
                (
                    {"heroId": radiant, "time": minute, "matchCount": 100, "winCount": 55},
                    {"heroId": dire, "time": minute, "matchCount": 100, "winCount": 45},
                )
            )
        by_time[f"heroStatsByTime_{position}"] = rows
    return {
        "heroes_meta_positions": meta,
        "hero_stats_by_time_bracket": by_time,
        "synergy": {"matchUp_Prev_Week_1": []},
    }


class _DltvFixtureClient:
    def __init__(self, payload: dict, received_at: datetime) -> None:
        self._payload = payload
        self._received_at = received_at

    async def get_live(self, _valve_match_id: int) -> TimedPayload:
        return TimedPayload(
            payload=self._payload,
            request_started_at=self._received_at - timedelta(seconds=1),
            received_at=self._received_at,
        )


class _DotaPositionFixtureClient:
    def __init__(self, received_at: datetime) -> None:
        self._received_at = received_at

    async def execute(self, *, operation_name: str, query: str, variables: dict) -> TimedPayload:
        players = []
        for is_radiant, account_start, hero_start in ((True, 1000, 0), (False, 2000, 100)):
            for position in range(1, 6):
                players.append(
                    {
                        "steamAccountId": account_start + position,
                        "heroId": hero_start + position,
                        "position": f"POSITION_{position}",
                        "isRadiant": is_radiant,
                    }
                )
        return TimedPayload(
            payload={"data": {"match": {"id": variables["matchId"], "players": players}}},
            request_started_at=self._received_at - timedelta(milliseconds=100),
            received_at=self._received_at,
        )


class _AiFixtureProvider:
    def __init__(self, name: str, *, timeout: bool = False) -> None:
        self.name = name
        self.model = f"fixture-{name}-v1"
        self._timeout = timeout
        self.inputs: list[str] = []

    async def decide(self, snapshot_input: str) -> AiProviderResponse:
        self.inputs.append(snapshot_input)
        if self._timeout:
            await asyncio.sleep(0.1)
        return AiProviderResponse(
            raw_response={"source": "production-replay"},
            decision=AiDecision(
                action="NO_BUY",
                fair_probability_a=None,
                confidence=0.5,
                market_assessment="UNKNOWN",
                minimum_acceptable_odds_a=None,
                primary_reasons=["recorded fixture"],
                counter_arguments=["recorded fixture can be incomplete"],
                data_quality_concerns=[],
                blockers=[],
            ),
            model_version=self.model,
        )

    async def close(self) -> None:
        return None


class _HistoricalFixtureProvider:
    normalizer_version = "production-replay-opendota-v1"

    def __init__(self, name: str, *, received_at: datetime, fail: bool) -> None:
        self.name = name
        self._received_at = received_at
        self._fail = fail
        self.team_ids: list[str] = []

    async def get_team_pro_maps(
        self, team_id: str, *, before: datetime, limit: int
    ) -> TimedPayload:
        self.team_ids.append(team_id)
        if self._fail:
            raise TimeoutError(f"{self.name} fixture timeout")
        return self._timed({"matches": [{"match_id": HISTORICAL_MATCH_ID}]})

    async def get_match_advanced(self, match_id: int) -> TimedPayload:
        if self._fail:
            raise TimeoutError(f"{self.name} fixture timeout")
        payload = deepcopy(_fixture("opendota_match.json"))
        payload["match_id"] = match_id
        payload["start_time"] = int((self._received_at - timedelta(days=1)).timestamp())
        return self._timed(payload)

    def normalize_match(self, payload: dict, *, fetched_at: datetime):
        return normalize_opendota_match(payload, fetched_at=fetched_at)

    def _timed(self, payload: dict) -> TimedPayload:
        return TimedPayload(
            payload=payload,
            request_started_at=self._received_at - timedelta(seconds=1),
            received_at=self._received_at,
        )


def _raybet_message(
    *,
    price_a: str,
    price_b: str,
    provider_updated_at: int,
    include_b: bool = True,
) -> dict:
    odds = [
        {
            "id": 75240285,
            "match_id": RAYBET_MATCH_ID,
            "odds": price_a,
            "last_update": str(provider_updated_at),
            "status": 1,
        }
    ]
    if include_b:
        odds.append(
            {
                "id": 75240286,
                "match_id": RAYBET_MATCH_ID,
                "odds": price_b,
                "last_update": str(provider_updated_at),
                "status": 1,
            }
        )
    return {
        "event": "#publish",
        "data": {"channel": "match", "data": {"source": "odds", "odds": odds}},
    }


async def _temporary_postgres_database() -> tuple[str, object]:
    source_url = os.environ.get("DATABASE_URL", Settings().database_url)
    parsed = make_url(source_url)
    database_name = f"dota_ai_replay_{uuid4().hex[:12]}"
    admin_url = parsed.set(database="postgres")
    admin_engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    async with admin_engine.connect() as connection:
        await connection.execute(text(f'CREATE DATABASE "{database_name}"'))
    return parsed.set(database=database_name).render_as_string(hide_password=False), admin_engine


async def _migrate(database_url: str) -> None:
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = database_url
    get_settings.cache_clear()
    try:
        await asyncio.to_thread(
            command.upgrade,
            AlembicConfig(str(ROOT / "alembic.ini")),
            "head",
        )
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
        get_settings.cache_clear()


async def _drop_temporary_database(database_url: str, admin_engine) -> None:
    database_name = make_url(database_url).database
    async with admin_engine.connect() as connection:
        await connection.execute(
            text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = :database_name AND pid <> pg_backend_pid()"
            ),
            {"database_name": database_name},
        )
        await connection.execute(text(f'DROP DATABASE "{database_name}"'))
    await admin_engine.dispose()


@pytest.mark.asyncio
async def test_production_lifecycle_replay_uses_postgres_and_converges() -> None:
    database_url, admin_engine = await _temporary_postgres_database()
    await _migrate(database_url)
    settings = Settings(database_url=database_url)
    engine = create_async_engine(database_url, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.connect() as connection:
            assert await connection.scalar(text("select 1")) == 1
            revision = await connection.scalar(text("select version_num from alembic_version"))
            assert revision == "0038_runtime_configuration"

        start = datetime.now(UTC).replace(microsecond=0)
        raw_events = RawEventRepository()
        events = EventRepository()
        identities = IdentityResolver()
        dltv = DltvBootstrapCoordinator(
            client=_DltvFixtureClient(_fixture("dltv_bootstrap.json"), start),
            raw_events=raw_events,
            events=events,
            identities=identities,
            role_assignment=DraftRoleAssignmentService(
                stratz=_DotaPositionFixtureClient(start + timedelta(seconds=1)),
                raw_events=raw_events,
            ),
        )
        raybet = RayBetOddsCollector(
            raw_events=raw_events,
            registry=OddsRegistry(),
            events=events,
            significant_move=settings.significant_odds_move,
        )
        async with factory() as session, session.begin():
            bootstrap = await dltv.bootstrap(session, valve_match_id=VALVE_MATCH_ID)
            resolved = bootstrap.resolved
        async with factory() as session, session.begin():
            session.add_all(
                [
                    ProviderTeamMapping(
                        provider="raybet",
                        provider_team_id="901",
                        canonical_team_id=resolved.team_a_id,
                        observed_name="Radiant Sample",
                    ),
                    ProviderTeamMapping(
                        provider="raybet",
                        provider_team_id="902",
                        canonical_team_id=resolved.team_b_id,
                        observed_name="Dire Sample",
                    ),
                    ProviderTeamMapping(
                        provider="stratz",
                        provider_team_id="100",
                        canonical_team_id=resolved.team_a_id,
                    ),
                    ProviderTeamMapping(
                        provider="stratz",
                        provider_team_id="200",
                        canonical_team_id=resolved.team_b_id,
                    ),
                    ProviderTeamMapping(
                        provider="opendota",
                        provider_team_id="100",
                        canonical_team_id=resolved.team_a_id,
                    ),
                    ProviderTeamMapping(
                        provider="opendota",
                        provider_team_id="200",
                        canonical_team_id=resolved.team_b_id,
                    ),
                    ProviderMatchMapping(
                        provider="raybet",
                        provider_match_id=str(RAYBET_MATCH_ID),
                        canonical_series_id=resolved.canonical_series_id,
                        canonical_map_id=resolved.canonical_map_id,
                        valve_match_id=VALVE_MATCH_ID,
                        resolved_by="PRODUCTION_REPLAY",
                        confidence=1.0,
                    ),
                    RayBetOddsRegistry(
                        odds_id=75240285,
                        provider_match_id=RAYBET_MATCH_ID,
                        team_id=901,
                        team_name="Radiant Sample",
                        group_short_name="Winner",
                        match_stage="Map r2",
                        raw_status=1,
                        raw_event_id=uuid4(),
                        refreshed_at=start,
                    ),
                    RayBetOddsRegistry(
                        odds_id=75240286,
                        provider_match_id=RAYBET_MATCH_ID,
                        team_id=902,
                        team_name="Dire Sample",
                        group_short_name="Winner",
                        match_stage="Map r2",
                        raw_status=1,
                        raw_event_id=uuid4(),
                        refreshed_at=start,
                    ),
                ]
            )
            await session.flush()

        historical_primary = _HistoricalFixtureProvider(
            "stratz", received_at=start - timedelta(seconds=2), fail=True
        )
        historical_fallback = _HistoricalFixtureProvider(
            "opendota", received_at=start - timedelta(seconds=2), fail=False
        )
        historical_sync = HistoricalSyncService(
            primary=historical_primary,
            fallback=historical_fallback,
            raw_events=raw_events,
            repository=HistoricalRepository(),
        )
        async with factory() as session, session.begin():
            sync_results = [
                await historical_sync.sync_team(
                    session,
                    canonical_team_id=team_id,
                    before=start,
                    limit=1,
                )
                for team_id in (resolved.team_a_id, resolved.team_b_id)
            ]
            assert all(result.provider == "opendota" for result in sync_results)
            assert sum(result.maps_requested for result in sync_results) == 1
            assert sum(result.maps_normalized for result in sync_results) == 1
            assert sum(result.maps_canonicalized for result in sync_results) == 1
            assert sum(result.provider_fallback_count for result in sync_results) == 1
            assert all(result.identity_missing_count == 0 for result in sync_results)
            assert historical_primary.team_ids == ["100", "200"]
            assert historical_fallback.team_ids == ["100", "200"]

        snapshots = SnapshotRepository()
        builder = SnapshotBuilder(
            settings=settings,
            history=HistoricalIntelligenceService(),
            repository=snapshots,
        )
        initial_market = _raybet_message(
            price_a="2.00",
            price_b="2.00",
            provider_updated_at=1_786_467_681,
        )
        async with factory() as session, session.begin():
            assert await raybet.collect(session, initial_market, received_at=start) == 2
            assert (
                await raybet.collect(
                    session,
                    initial_market,
                    received_at=start + timedelta(seconds=1),
                )
                == 0
            )
            unknown_market = deepcopy(initial_market)
            unknown_market["data"]["data"]["odds"] = [
                {
                    "id": 99999999,
                    "match_id": RAYBET_MATCH_ID,
                    "odds": "1.75",
                    "last_update": "1786467682",
                    "status": 1,
                }
            ]
            assert (
                await raybet.collect(
                    session,
                    unknown_market,
                    received_at=start + timedelta(seconds=2),
                )
                == 0
            )
            prematch_outcome = await builder.build(
                session,
                canonical_series_id=resolved.canonical_series_id,
                decision_at=start + timedelta(seconds=2),
            )
            assert prematch_outcome.snapshot is not None
            assert prematch_outcome.snapshot.mode.value == "PREMATCH"
            prematch_payload = deepcopy(
                (
                    await session.get(
                        DecisionSnapshotRecord,
                        prematch_outcome.snapshot.snapshot_id,
                    )
                ).canonical_payload
            )

        async with factory() as session, session.begin():
            draft = await session.scalar(
                select(DraftSnapshotRecord)
                .where(DraftSnapshotRecord.canonical_map_id == resolved.canonical_map_id)
                .order_by(DraftSnapshotRecord.observed_at.desc())
                .limit(1)
            )
            assert draft is not None and draft.complete is True
            rosh_result = score_rosh_lineups(
                [1, 2, 3, 4, 5],
                [101, 102, 103, 104, 105],
                _analysis(),
            )
            curve = build_draft_curve(
                rosh_result,
                current_minute=18,
                statistics_cutoff=start,
                data_version="production-replay-v1",
            )
            session.add(
                DraftMinuteCurveRecord(
                    canonical_map_id=resolved.canonical_map_id,
                    draft_snapshot_id=draft.id,
                    points=[point.model_dump(mode="json") for point in curve.points],
                    derived_features=curve.features.model_dump(mode="json"),
                    statistics_cutoff=curve.statistics_cutoff,
                    calculated_at=start + timedelta(seconds=3),
                    model_version=curve.model_version,
                    data_version=curve.data_version,
                )
            )
            await session.flush()
            post_draft_outcome = await builder.build(
                session,
                canonical_map_id=resolved.canonical_map_id,
                decision_at=start + timedelta(seconds=4),
            )
            assert post_draft_outcome.snapshot is not None
            assert post_draft_outcome.snapshot.mode.value == "POST_DRAFT"
            post_draft_payload = deepcopy(
                (
                    await session.get(
                        DecisionSnapshotRecord,
                        post_draft_outcome.snapshot.snapshot_id,
                    )
                ).canonical_payload
            )

        for message, offset in (
            (
                _raybet_message(
                    price_a="2.20",
                    price_b="2.00",
                    provider_updated_at=1_786_467_691,
                    include_b=False,
                ),
                10,
            ),
            (
                _raybet_message(
                    price_a="1.90",
                    price_b="2.00",
                    provider_updated_at=1_786_467_701,
                    include_b=False,
                ),
                20,
            ),
        ):
            async with factory() as session, session.begin():
                await raybet.collect(
                    session,
                    message,
                    received_at=start + timedelta(seconds=offset),
                )

        dltv_collector = DltvSocketCollector(
            session_factory=factory,
            raw_events=raw_events,
            events=events,
        )
        await dltv_collector.collect(
            f"__nd2_match_{VALVE_MATCH_ID}",
            {"game_time": 1062, "radiant_score": 11},
            "connection-1",
            1,
            received_at=start + timedelta(seconds=11),
        )
        await dltv_collector.collect(
            f"__nd2_match_{VALVE_MATCH_ID}",
            {"game_time": 1062, "radiant_score": 11},
            "connection-2",
            2,
            received_at=start + timedelta(seconds=12),
        )
        await dltv_collector.collect(
            f"__nd2_match_{VALVE_MATCH_ID}",
            {"game_time": 1072, "radiant_score": 12, "dire_score": 10, "radiant_lead": -5600},
            "connection-2",
            2,
            received_at=start + timedelta(seconds=21),
        )
        async with factory() as session, session.begin():
            await raybet.collect(
                session,
                _raybet_message(
                    price_a="2.20",
                    price_b="2.00",
                    provider_updated_at=1_786_467_711,
                ),
                received_at=start + timedelta(seconds=30),
            )
        await dltv_collector.collect(
            f"__nd2_match_{VALVE_MATCH_ID}",
            {"game_time": 1082, "radiant_score": 13, "dire_score": 10, "radiant_lead": -4500},
            "connection-2",
            2,
            received_at=start + timedelta(seconds=31),
        )

        async with factory() as session, session.begin():
            temporal = TemporalAligner(settings)
            estimate = await temporal.calculate(
                session,
                canonical_map_id=resolved.canonical_map_id,
                as_of=start + timedelta(seconds=31),
            )
            assert estimate.status == "SAFE"
            assert estimate.sample_size == 3

            outcome = await builder.build(
                session,
                canonical_map_id=resolved.canonical_map_id,
                decision_at=start + timedelta(seconds=31),
            )
            assert outcome.snapshot is not None
            assert outcome.snapshot.mode.value == "LIVE_BASIC"
            snapshot_hash = outcome.snapshot.snapshot_hash

            providers = [_AiFixtureProvider("gpt"), _AiFixtureProvider("claude", timeout=True)]
            decisions = await AiCoordinator(providers, timeout_seconds=0.01).run_all(
                session, outcome.snapshot
            )
            assert {record.parse_status for record in decisions} == {"SUCCESS", "TIMEOUT"}
            assert len({provider.inputs[0] for provider in providers}) == 1

            closing = await FutureOddsService(
                JobRepository(),
                market_max_age_seconds=30,
                market_max_pair_skew_seconds=5,
            ).capture_closing(
                session,
                snapshot_id=outcome.snapshot.snapshot_id,
                triggered_at=start + timedelta(seconds=40),
            )
            assert closing.status == "CAPTURED"
            assert closing.capture_type == "CLOSING"
            assert closing.pair_quality["eligible"] is True

            result = await SettlementService().settle(
                session,
                canonical_map_id=resolved.canonical_map_id,
                winner_team_id=resolved.team_a_id,
                provider="opendota",
                provider_match_id=str(VALVE_MATCH_ID),
                result_observed_at=start + timedelta(seconds=50),
                basic_first_usable_at=start + timedelta(seconds=50),
                raw_event_id=uuid4(),
                normalizer_version="production-replay-v1",
                identity_confidence=1.0,
            )
            assert result.winner_team_id == resolved.team_a_id
            assert (
                await EvaluationService().evaluate_snapshot(
                    session, snapshot_id=outcome.snapshot.snapshot_id
                )
                == 1
            )

            job_repository = JobRepository()
            job_id = await job_repository.enqueue(
                session,
                job_type=JobType.BUILD_SNAPSHOT,
                dedupe_key=f"production-replay:{resolved.canonical_map_id}",
                payload={"canonical_map_id": str(resolved.canonical_map_id)},
                not_before=start,
            )
            claimed = await job_repository.claim(
                session,
                worker_id="replay-worker-1",
                now=start,
                job_types=(JobType.BUILD_SNAPSHOT,),
            )
            assert claimed and claimed[0].id == job_id
            assert (
                await job_repository.reclaim_expired(
                    session,
                    lease_seconds=30,
                    now=start + timedelta(seconds=31),
                )
                == 1
            )
            claimed_again = await job_repository.claim(
                session,
                worker_id="replay-worker-2",
                now=start + timedelta(seconds=31),
                job_types=(JobType.BUILD_SNAPSHOT,),
            )
            assert claimed_again and claimed_again[0].id == job_id
            await job_repository.succeed(
                session,
                job_id=job_id,
                worker_id="replay-worker-2",
                completed_at=start + timedelta(seconds=32),
            )

            persisted_snapshot = await session.get(
                DecisionSnapshotRecord, outcome.snapshot.snapshot_id
            )
            assert persisted_snapshot is not None
            assert persisted_snapshot.snapshot_hash == snapshot_hash
            assert persisted_snapshot.canonical_payload["mode"] == "LIVE_BASIC"
            assert (
                await session.get(
                    DecisionSnapshotRecord,
                    prematch_outcome.snapshot.snapshot_id,
                )
            ).canonical_payload == prematch_payload
            assert (
                await session.get(
                    DecisionSnapshotRecord,
                    post_draft_outcome.snapshot.snapshot_id,
                )
            ).canonical_payload == post_draft_payload
            snapshot_records = list(
                (
                    await session.scalars(
                        select(DecisionSnapshotRecord).order_by(DecisionSnapshotRecord.decision_at)
                    )
                ).all()
            )
            assert [record.mode for record in snapshot_records] == [
                "PREMATCH",
                "POST_DRAFT",
                "LIVE_BASIC",
            ]
            assert await session.scalar(select(func.count()).select_from(ProviderRawEvent)) >= 14
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(ProviderRawEvent)
                    .where(ProviderRawEvent.provider == "raybet")
                )
                == 6
            )
            assert (
                await session.scalar(select(func.count()).select_from(OddsObservationRecord)) == 6
            )
            assert (
                await session.scalar(select(func.count()).select_from(DltvLiveObservationRecord))
                == 4
            )
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(DomainEventRecord)
                    .where(DomainEventRecord.event_type == "ODDS_REGISTRY_REFRESH_REQUIRED")
                )
                == 1
            )
            assert await session.scalar(select(func.count()).select_from(HistoricalMapRecord)) == 1
            assert await session.scalar(select(func.count()).select_from(AiDecisionRecord)) == 2
            assert await session.scalar(select(func.count()).select_from(DecisionFutureOdds)) == 1
            assert (
                await session.scalar(select(func.count()).select_from(DecisionEvaluationRecord))
                == 1
            )
            job_statuses = set((await session.scalars(select(DurableJobRecord.status))).all())
            assert job_statuses == {"SUCCEEDED"}
    finally:
        await engine.dispose()
        await _drop_temporary_database(database_url, admin_engine)
