import asyncio
from pathlib import Path
from uuid import UUID

from fastapi import FastAPI, HTTPException, Response, WebSocket, WebSocketDisconnect
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
    DecisionSnapshotRecord,
    DltvLiveObservationRecord,
    DraftMinuteCurveRecord,
    DraftSnapshotRecord,
    DurableJobRecord,
    LiveSyncEstimateRecord,
    OddsObservationRecord,
)
from app.runtime.health import HealthRegistry


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

    @app.get("/api/maps")
    async def maps() -> list[dict]:
        async with session_factory() as session:
            records = list(
                (
                    await session.scalars(
                        select(CanonicalMap).order_by(CanonicalMap.scheduled_at.desc()).limit(24)
                    )
                ).all()
            )
            return [await _map_payload(session, record) for record in records]

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
                await websocket.send_json(await health.snapshot())
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
    payload = {
        "id": canonical_map.id,
        "series_id": canonical_map.series_id,
        "map_number": canonical_map.map_number,
        "valve_match_id": canonical_map.valve_match_id,
        "scheduled_at": canonical_map.scheduled_at,
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
            }
            for item in latest_odds.values()
        ],
        "draft": (
            {
                "complete": draft.complete,
                "blockers": draft.blockers,
                "warnings": draft.warnings,
                "observed_at": draft.observed_at,
                "features": curve.derived_features if curve else None,
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
            }
            if sync
            else None
        ),
        "latest_snapshot": (
            {
                "id": snapshot.id,
                "decision_at": snapshot.decision_at,
                "mode": snapshot.mode,
                "snapshot_hash": snapshot.snapshot_hash,
                "quality": snapshot.canonical_payload.get("quality"),
            }
            if snapshot
            else None
        ),
        "decisions": [_decision_payload(item) for item in decisions],
    }
    if detailed and snapshot is not None:
        payload["snapshot_payload"] = snapshot.canonical_payload
    if detailed:
        payload["market_timeline"] = [
            {
                "odds_id": item.odds_id,
                "selection_team_id": item.selection_team_id,
                "price": item.price,
                "fair_probability": item.fair_probability,
                "raw_status": item.raw_status,
                "provider_updated_at": item.provider_updated_at,
                "received_at": item.received_at,
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
            }
            for item in reversed(live_rows)
        ]
        if curve is not None and payload["draft"] is not None:
            payload["draft"]["curve"] = curve.points
            payload["draft"]["model_version"] = curve.model_version
            payload["draft"]["data_version"] = curve.data_version
    return payload


def _decision_payload(record: AiDecisionRecord) -> dict:
    return {
        "id": record.id,
        "provider": record.provider,
        "model": record.model,
        "model_version": record.model_version,
        "parse_status": record.parse_status,
        "latency_seconds": record.latency_seconds,
        "decision": record.normalized_response,
        "error": record.error,
    }
