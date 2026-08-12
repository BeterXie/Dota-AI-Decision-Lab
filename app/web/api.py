import asyncio
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from fastapi import FastAPI, HTTPException, Response, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import (
    AiDecisionRecord,
    CanonicalMap,
    CanonicalSeries,
    CanonicalTeam,
    DecisionFutureOdds,
    DecisionSnapshotRecord,
    DltvLiveObservationRecord,
    DraftMinuteCurveRecord,
    DraftSnapshotRecord,
    DurableJobRecord,
    LiveSyncEstimateRecord,
    MapResultEvidenceRecord,
    MapResultRecord,
    OddsObservationRecord,
    ProviderMatchMapping,
    RayBetMatch,
)
from app.runtime.health import HealthRegistry
from app.time import elapsed_seconds


def create_app(
    session_factory: async_sessionmaker[AsyncSession],
    health: HealthRegistry,
    *,
    frontend_dist: Path | None = None,
) -> FastAPI:
    app = FastAPI(title="Dota AI Decision Lab", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def process_health() -> dict:
        return {"status": "RUNNING"}

    @app.get("/ready")
    async def readiness(response: Response) -> dict:
        snapshot = await health.snapshot()
        if snapshot["overall"] == "ACTION_REQUIRED":
            response.status_code = 503
        return snapshot

    @app.get("/api/runtime")
    async def runtime() -> dict:
        return await health.snapshot()

    @app.get("/api/matches")
    async def matches() -> list[dict]:
        async with session_factory() as session:
            map_records = list(
                (
                    await session.scalars(
                        select(CanonicalMap).order_by(CanonicalMap.scheduled_at.desc()).limit(24)
                    )
                ).all()
            )
            pending_series = list(
                (
                    await session.scalars(
                        select(CanonicalSeries)
                        .where(
                            ~select(CanonicalMap.id)
                            .where(CanonicalMap.series_id == CanonicalSeries.id)
                            .exists()
                        )
                        .order_by(CanonicalSeries.scheduled_at.desc())
                        .limit(24)
                    )
                ).all()
            )
            payloads = [await _map_payload(session, record) for record in map_records]
            for series in pending_series:
                payload = await _pending_series_payload(session, series)
                if payload is not None:
                    payloads.append(payload)
            payloads.sort(
                key=lambda item: item["scheduled_at"]
                or item.get("provider_observed_at")
                or datetime.min.replace(tzinfo=UTC),
                reverse=True,
            )
            return payloads[:24]

    @app.get("/api/maps/{canonical_map_id}")
    async def map_detail(canonical_map_id: UUID) -> dict:
        async with session_factory() as session:
            record = await session.get(CanonicalMap, canonical_map_id)
            if record is None:
                raise HTTPException(status_code=404, detail="map not found")
            return await _map_payload(session, record, detailed=True)

    @app.get("/api/snapshots/{snapshot_id}")
    async def snapshot_detail(snapshot_id: UUID) -> dict:
        async with session_factory() as session:
            snapshot = await session.get(DecisionSnapshotRecord, snapshot_id)
            if snapshot is None:
                raise HTTPException(status_code=404, detail="snapshot not found")
            decisions = list(
                (
                    await session.scalars(
                        select(AiDecisionRecord).where(AiDecisionRecord.snapshot_id == snapshot.id)
                    )
                ).all()
            )
            return {
                "id": snapshot.id,
                "decision_at": snapshot.decision_at,
                "created_at": snapshot.created_at,
                "mode": snapshot.mode,
                "snapshot_hash": snapshot.snapshot_hash,
                "payload": snapshot.canonical_payload,
                "decisions": [_decision_payload(item) for item in decisions],
            }

    @app.get("/api/jobs/summary")
    async def job_summary() -> dict:
        async with session_factory() as session:
            by_status = {
                status: count
                for status, count in (
                    await session.execute(
                        select(DurableJobRecord.status, func.count())
                        .group_by(DurableJobRecord.status)
                        .order_by(DurableJobRecord.status)
                    )
                ).all()
            }
            by_type = [
                {"job_type": job_type, "status": status, "count": count}
                for job_type, status, count in (
                    await session.execute(
                        select(
                            DurableJobRecord.job_type,
                            DurableJobRecord.status,
                            func.count(),
                        )
                        .group_by(DurableJobRecord.job_type, DurableJobRecord.status)
                        .order_by(DurableJobRecord.job_type, DurableJobRecord.status)
                    )
                ).all()
            ]
            recent_failures = list(
                (
                    await session.scalars(
                        select(DurableJobRecord)
                        .where(DurableJobRecord.status == "FAILED_TERMINAL")
                        .order_by(DurableJobRecord.completed_at.desc())
                        .limit(12)
                    )
                ).all()
            )
            oldest_pending = await session.scalar(
                select(func.min(DurableJobRecord.created_at)).where(
                    DurableJobRecord.status.in_(("PENDING", "RETRY_WAIT", "RUNNING"))
                )
            )
            return {
                "by_status": by_status,
                "by_type": by_type,
                "oldest_pending_at": oldest_pending,
                "recent_failures": [
                    {
                        "id": item.id,
                        "job_type": item.job_type,
                        "dedupe_key": item.dedupe_key,
                        "attempt_count": item.attempt_count,
                        "last_error": item.last_error,
                        "completed_at": item.completed_at,
                    }
                    for item in recent_failures
                ],
            }

    @app.get("/metrics")
    async def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.websocket("/ws/status")
    async def status_socket(websocket: WebSocket) -> None:
        await websocket.accept()
        try:
            while True:
                await websocket.send_json(jsonable_encoder(await health.snapshot()))
                await asyncio.sleep(2)
        except WebSocketDisconnect:
            return

    if frontend_dist is not None and frontend_dist.is_dir():
        assets = frontend_dist / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{full_path:path}")
        async def frontend(full_path: str) -> FileResponse:
            candidate = frontend_dist / full_path
            if full_path and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(frontend_dist / "index.html")

    return app


async def _map_payload(
    session: AsyncSession, canonical_map: CanonicalMap, *, detailed: bool = False
) -> dict:
    series = (
        await session.get(CanonicalSeries, canonical_map.series_id)
        if canonical_map.series_id is not None
        else None
    )
    team_a = await session.get(CanonicalTeam, series.team_a_id) if series else None
    team_b = await session.get(CanonicalTeam, series.team_b_id) if series else None
    raybet_match = await _latest_raybet_match(session, canonical_map.series_id)
    odds = list(
        (
            await session.scalars(
                select(OddsObservationRecord)
                .where(
                    or_(
                        OddsObservationRecord.canonical_map_id == canonical_map.id,
                        OddsObservationRecord.canonical_series_id == canonical_map.series_id,
                    )
                )
                .order_by(OddsObservationRecord.received_at.desc())
                .limit(64)
            )
        ).all()
    )
    latest_odds: dict[int, OddsObservationRecord] = {}
    for observation in odds:
        latest_odds.setdefault(observation.odds_id, observation)
    team_order = {
        team_id: index
        for index, team_id in enumerate(
            (series.team_a_id, series.team_b_id) if series is not None else ()
        )
    }
    current_market = sorted(
        latest_odds.values(),
        key=lambda item: (team_order.get(item.selection_team_id, 2), item.odds_id),
    )
    draft = await session.scalar(
        select(DraftSnapshotRecord)
        .where(DraftSnapshotRecord.canonical_map_id == canonical_map.id)
        .order_by(DraftSnapshotRecord.observed_at.desc())
        .limit(1)
    )
    curve = (
        await session.scalar(
            select(DraftMinuteCurveRecord)
            .where(DraftMinuteCurveRecord.draft_snapshot_id == draft.id)
            .order_by(DraftMinuteCurveRecord.calculated_at.desc())
            .limit(1)
        )
        if draft is not None
        else None
    )
    live_rows = list(
        (
            await session.scalars(
                select(DltvLiveObservationRecord)
                .where(DltvLiveObservationRecord.canonical_map_id == canonical_map.id)
                .order_by(DltvLiveObservationRecord.received_at.desc())
                .limit(120 if detailed else 1)
            )
        ).all()
    )
    live = live_rows[0] if live_rows else None
    sync = await session.scalar(
        select(LiveSyncEstimateRecord)
        .where(LiveSyncEstimateRecord.canonical_map_id == canonical_map.id)
        .order_by(LiveSyncEstimateRecord.calculated_at.desc())
        .limit(1)
    )
    snapshot = await session.scalar(
        select(DecisionSnapshotRecord)
        .where(DecisionSnapshotRecord.canonical_map_id == canonical_map.id)
        .order_by(DecisionSnapshotRecord.decision_at.desc())
        .limit(1)
    )
    decisions = (
        list(
            (
                await session.scalars(
                    select(AiDecisionRecord).where(AiDecisionRecord.snapshot_id == snapshot.id)
                )
            ).all()
        )
        if snapshot is not None
        else []
    )
    future_odds = []
    result = None
    result_evidence = []
    if detailed:
        if snapshot is not None:
            future_odds = list(
                (
                    await session.scalars(
                        select(DecisionFutureOdds)
                        .where(DecisionFutureOdds.decision_snapshot_id == snapshot.id)
                        .order_by(DecisionFutureOdds.triggered_at)
                    )
                ).all()
            )
        result = await session.scalar(
            select(MapResultRecord).where(MapResultRecord.canonical_map_id == canonical_map.id)
        )
        result_evidence = list(
            (
                await session.scalars(
                    select(MapResultEvidenceRecord)
                    .where(MapResultEvidenceRecord.canonical_map_id == canonical_map.id)
                    .order_by(MapResultEvidenceRecord.first_usable_at)
                )
            ).all()
        )
    observed_at = datetime.now(UTC)
    snapshot_market = snapshot.canonical_payload.get("market", {}) if snapshot is not None else {}
    snapshot_quality = snapshot.canonical_payload.get("quality", {}) if snapshot is not None else {}
    payload = {
        "entity_type": "MAP",
        "identity_status": "RESOLVED",
        "id": canonical_map.id,
        "series_id": canonical_map.series_id,
        "canonical_map_id": canonical_map.id,
        "map_number": canonical_map.map_number,
        "valve_match_id": canonical_map.valve_match_id,
        "scheduled_at": canonical_map.scheduled_at,
        "provider_match_id": raybet_match.provider_match_id if raybet_match else None,
        "tournament_name": raybet_match.tournament_name if raybet_match else None,
        "round": raybet_match.round if raybet_match else None,
        "raw_status": raybet_match.raw_status if raybet_match else None,
        "provider_observed_at": raybet_match.observed_at if raybet_match else None,
        "team_a": {"id": team_a.id, "name": team_a.name} if team_a else None,
        "team_b": {"id": team_b.id, "name": team_b.name} if team_b else None,
        "market": [
            {
                "odds_id": item.odds_id,
                "selection_team_id": item.selection_team_id,
                "price": item.price,
                "fair_probability": item.fair_probability,
                "raw_status": item.raw_status,
                "received_at": item.received_at,
                "normalized_status": item.normalized_status,
                "metadata_version": item.metadata_version,
                "provider_updated_at": item.provider_updated_at,
                "age_seconds": elapsed_seconds(observed_at, item.received_at),
                "market_type": item.market_type,
                "match_stage": item.match_stage,
            }
            for item in current_market
        ],
        "market_quality": (
            snapshot_market.get("quality") if isinstance(snapshot_market, dict) else None
        ),
        "draft": (
            {
                "complete": draft.complete,
                "blockers": draft.blockers,
                "warnings": draft.warnings,
                "observed_at": draft.observed_at,
                "statistics_cutoff": draft.statistics_cutoff,
                "features": curve.derived_features if curve else None,
                "model_version": curve.model_version if curve else None,
                "data_version": curve.data_version if curve else None,
            }
            if draft
            else None
        ),
        "live": (
            {
                "game_time_seconds": live.game_time_seconds,
                "radiant_kills": live.radiant_kills,
                "dire_kills": live.dire_kills,
                "radiant_nw_lead": live.radiant_nw_lead,
                "received_at": live.received_at,
                "last_message_received_at": live.last_message_received_at,
                "last_state_change_received_at": live.last_state_change_received_at,
                "message_age_seconds": elapsed_seconds(observed_at, live.last_message_received_at),
                "effective_state_age_seconds": elapsed_seconds(
                    observed_at, live.last_state_change_received_at
                ),
                "connection_id": live.connection_id,
                "reconnect_generation": live.reconnect_generation,
            }
            if live
            else None
        ),
        "sync": (
            {
                "status": sync.status,
                "p50_seconds": sync.p50_seconds,
                "p90_seconds": sync.p90_seconds,
                "jitter_seconds": sync.jitter_seconds,
                "sample_size": sync.sample_size,
                "accepted_pair_ratio": sync.accepted_pair_ratio,
                "ambiguous_ratio": sync.ambiguous_ratio,
                "outlier_ratio": sync.outlier_ratio,
                "confidence": sync.confidence,
                "calculated_at": sync.calculated_at,
            }
            if sync
            else None
        ),
        "latest_snapshot": (
            {
                "id": snapshot.id,
                "decision_at": snapshot.decision_at,
                "created_at": snapshot.created_at,
                "mode": snapshot.mode,
                "snapshot_hash": snapshot.snapshot_hash,
                "quality": snapshot_quality,
                "market_quality": (
                    snapshot_market.get("quality") if isinstance(snapshot_market, dict) else None
                ),
                "history_coverage": snapshot.canonical_payload.get("history", {}).get("coverage"),
            }
            if snapshot
            else None
        ),
        "decisions": [_decision_payload(item) for item in decisions],
    }
    if detailed and snapshot is not None:
        payload["snapshot_payload"] = snapshot.canonical_payload
        payload["future_odds"] = [_future_odds_payload(item) for item in future_odds]
    elif detailed:
        payload["future_odds"] = []
    if detailed:
        payload["market_timeline"] = [
            {
                "odds_id": item.odds_id,
                "selection_team_id": item.selection_team_id,
                "price": item.price,
                "fair_probability": item.fair_probability,
                "raw_status": item.raw_status,
                "normalized_status": item.normalized_status,
                "metadata_version": item.metadata_version,
                "market_type": item.market_type,
                "match_stage": item.match_stage,
                "provider_updated_at": item.provider_updated_at,
                "received_at": item.received_at,
                "age_seconds": elapsed_seconds(observed_at, item.received_at),
            }
            for item in reversed(odds)
        ]
        payload["live_timeline"] = [
            {
                "game_time_seconds": item.game_time_seconds,
                "radiant_kills": item.radiant_kills,
                "dire_kills": item.dire_kills,
                "radiant_nw_lead": item.radiant_nw_lead,
                "received_at": item.received_at,
                "last_message_received_at": item.last_message_received_at,
                "last_state_change_received_at": item.last_state_change_received_at,
                "connection_id": item.connection_id,
                "reconnect_generation": item.reconnect_generation,
            }
            for item in reversed(live_rows)
        ]
        if curve is not None and payload["draft"] is not None:
            payload["draft"]["curve"] = curve.points
        payload["result"] = (
            {
                "winner_team_id": result.winner_team_id,
                "basic_first_usable_at": result.basic_first_usable_at,
                "advanced_first_usable_at": result.advanced_first_usable_at,
                "settled_at": result.settled_at,
                "provider_conflict": result.provider_conflict,
            }
            if result is not None
            else None
        )
        payload["result_evidence"] = [
            {
                "id": item.id,
                "provider": item.provider,
                "provider_match_id": item.provider_match_id,
                "winner_team_id": item.winner_team_id,
                "result_observed_at": item.result_observed_at,
                "first_usable_at": item.first_usable_at,
                "raw_event_id": item.raw_event_id,
                "normalizer_version": item.normalizer_version,
                "identity_confidence": item.identity_confidence,
                "conflict_status": item.conflict_status,
            }
            for item in result_evidence
        ]
    return payload


async def _pending_series_payload(
    session: AsyncSession, series: CanonicalSeries
) -> dict | None:
    raybet_match = await _latest_raybet_match(session, series.id)
    if raybet_match is None:
        return None
    team_a = await session.get(CanonicalTeam, series.team_a_id)
    team_b = await session.get(CanonicalTeam, series.team_b_id)
    odds = list(
        (
            await session.scalars(
                select(OddsObservationRecord)
                .where(OddsObservationRecord.canonical_series_id == series.id)
                .order_by(OddsObservationRecord.received_at.desc())
                .limit(64)
            )
        ).all()
    )
    latest_odds: dict[int, OddsObservationRecord] = {}
    for observation in odds:
        latest_odds.setdefault(observation.odds_id, observation)
    team_order = {
        team_id: index
        for index, team_id in enumerate((series.team_a_id, series.team_b_id))
    }
    current_market = sorted(
        latest_odds.values(),
        key=lambda item: (team_order.get(item.selection_team_id, 2), item.odds_id),
    )
    observed_at = datetime.now(UTC)
    return {
        "entity_type": "SERIES",
        "identity_status": "PENDING_MAP_IDENTITY",
        "id": series.id,
        "series_id": series.id,
        "canonical_map_id": None,
        "map_number": None,
        "valve_match_id": None,
        "scheduled_at": series.scheduled_at,
        "provider_match_id": raybet_match.provider_match_id,
        "tournament_name": raybet_match.tournament_name,
        "round": raybet_match.round,
        "raw_status": raybet_match.raw_status,
        "provider_observed_at": raybet_match.observed_at,
        "team_a": {"id": team_a.id, "name": team_a.name} if team_a else None,
        "team_b": {"id": team_b.id, "name": team_b.name} if team_b else None,
        "market": [
            {
                "odds_id": item.odds_id,
                "selection_team_id": item.selection_team_id,
                "price": item.price,
                "fair_probability": item.fair_probability,
                "raw_status": item.raw_status,
                "received_at": item.received_at,
                "normalized_status": item.normalized_status,
                "metadata_version": item.metadata_version,
                "provider_updated_at": item.provider_updated_at,
                "age_seconds": elapsed_seconds(observed_at, item.received_at),
                "market_type": item.market_type,
                "match_stage": item.match_stage,
            }
            for item in current_market
        ],
        "market_quality": None,
        "draft": None,
        "live": None,
        "sync": None,
        "latest_snapshot": None,
        "decisions": [],
    }


async def _latest_raybet_match(
    session: AsyncSession, series_id: UUID | None
) -> RayBetMatch | None:
    if series_id is None:
        return None
    provider_match_id = await session.scalar(
        select(ProviderMatchMapping.provider_match_id)
        .where(
            ProviderMatchMapping.provider == "raybet",
            ProviderMatchMapping.canonical_series_id == series_id,
        )
        .limit(1)
    )
    if provider_match_id is None:
        return None
    return await session.scalar(
        select(RayBetMatch)
        .where(RayBetMatch.provider_match_id == int(provider_match_id))
        .order_by(RayBetMatch.observed_at.desc())
        .limit(1)
    )


def _decision_payload(record: AiDecisionRecord) -> dict:
    return {
        "id": record.id,
        "provider": record.provider,
        "model": record.model,
        "model_version": record.model_version,
        "prompt_version": record.prompt_version,
        "decision_policy_version": record.decision_policy_version,
        "snapshot_hash": record.snapshot_hash,
        "request_started_at": record.request_started_at,
        "response_received_at": record.response_received_at,
        "parse_status": record.parse_status,
        "latency_seconds": record.latency_seconds,
        "decision": record.normalized_response,
        "error": record.error,
    }


def _future_odds_payload(record: DecisionFutureOdds) -> dict:
    return {
        "id": record.id,
        "capture_type": record.capture_type,
        "horizon_seconds": record.horizon_seconds,
        "triggered_at": record.triggered_at,
        "due_at": record.due_at,
        "observed_at": record.observed_at,
        "odds_a": record.odds_a,
        "odds_b": record.odds_b,
        "market_type": record.market_type,
        "match_stage": record.match_stage,
        "market_status": record.market_status,
        "capture_policy_version": record.capture_policy_version,
        "pair_quality": record.pair_quality,
        "pair_skew_seconds": record.pair_skew_seconds,
        "status": record.status,
    }
