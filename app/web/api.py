import asyncio
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from fastapi import FastAPI, HTTPException, Response, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.market import MarketPairQuality
from app.history.service import HistoricalIntelligenceService
from app.market.fair_probability import remove_vig
from app.market.pairing import MarketPairLeg, evaluate_market_pair
from app.models import (
    AiDecisionRecord,
    CanonicalEvent,
    CanonicalHero,
    CanonicalMap,
    CanonicalPlayer,
    CanonicalSeries,
    CanonicalTeam,
    DecisionFutureOdds,
    DecisionSnapshotRecord,
    DltvLiveObservationRecord,
    DraftMinuteCurveRecord,
    DraftSlotRecord,
    DraftSnapshotRecord,
    DurableJobRecord,
    LiveSyncEstimateRecord,
    MapResultEvidenceRecord,
    MapResultRecord,
    OddsObservationRecord,
    PlayerFormSnapshotRecord,
    PlayerHeroSnapshotRecord,
    ProviderMatchMapping,
    RayBetMatch,
)
from app.runtime.health import HealthRegistry
from app.time import elapsed_seconds, ensure_utc


def create_app(
    session_factory: async_sessionmaker[AsyncSession],
    health: HealthRegistry,
    *,
    frontend_dist: Path | None = None,
    live_state_max_age_seconds: float = 45.0,
    live_market_max_age_seconds: float = 30.0,
    market_max_pair_skew_seconds: float = 5.0,
) -> FastAPI:
    app = FastAPI(title="Dota AI Decision Lab", version="0.1.0")

    async def runtime_payload() -> dict:
        snapshot = await health.snapshot()
        return {
            **snapshot,
            "live_state_max_age_seconds": live_state_max_age_seconds,
            "live_market_max_age_seconds": live_market_max_age_seconds,
        }

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
        return await runtime_payload()

    @app.get("/api/matches")
    async def matches() -> list[dict]:
        async with session_factory() as session:
            live_providers = ("raybet", "dltv")
            map_records = list(
                (
                    await session.scalars(
                        select(CanonicalMap)
                        .outerjoin(CanonicalSeries, CanonicalSeries.id == CanonicalMap.series_id)
                        .where(
                            or_(
                                select(ProviderMatchMapping.id)
                                .where(
                                    ProviderMatchMapping.provider.in_(live_providers),
                                    or_(
                                        ProviderMatchMapping.canonical_map_id == CanonicalMap.id,
                                        ProviderMatchMapping.canonical_series_id
                                        == CanonicalMap.series_id,
                                    ),
                                )
                                .exists(),
                                select(DltvLiveObservationRecord.id)
                                .where(DltvLiveObservationRecord.canonical_map_id == CanonicalMap.id)
                                .exists(),
                                select(DecisionSnapshotRecord.id)
                                .where(DecisionSnapshotRecord.canonical_map_id == CanonicalMap.id)
                                .exists(),
                            )
                        )
                        # Maps resolved from DLTV identity usually carry no
                        # scheduled_at of their own; fall back to the series
                        # schedule so the newest matches sort first.
                        .order_by(
                            func.coalesce(CanonicalMap.scheduled_at, CanonicalSeries.scheduled_at)
                            .desc()
                            .nulls_last()
                        )
                        .limit(100)
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
                            .exists(),
                            select(ProviderMatchMapping.id)
                            .where(
                                ProviderMatchMapping.provider.in_(live_providers),
                                ProviderMatchMapping.canonical_series_id == CanonicalSeries.id,
                            )
                            .exists(),
                        )
                        .order_by(CanonicalSeries.scheduled_at.desc().nulls_last())
                        .limit(100)
                    )
                ).all()
            )
            payloads = await _map_summary_payloads(
                session,
                map_records,
                live_state_max_age_seconds=live_state_max_age_seconds,
                live_market_max_age_seconds=live_market_max_age_seconds,
                market_max_pair_skew_seconds=market_max_pair_skew_seconds,
            )
            for series in pending_series:
                payload = await _pending_series_payload(
                    session,
                    series,
                    live_market_max_age_seconds=live_market_max_age_seconds,
                    market_max_pair_skew_seconds=market_max_pair_skew_seconds,
                )
                if payload is not None:
                    payloads.append(payload)
            payloads.sort(
                key=lambda item: (
                    ensure_utc(item["scheduled_at"])
                    if item["scheduled_at"] is not None
                    else ensure_utc(datetime.min)
                ),
                reverse=True,
            )
            return payloads[:60]

    @app.get("/api/maps/{canonical_map_id}")
    async def map_detail(canonical_map_id: UUID) -> dict:
        async with session_factory() as session:
            record = await session.get(CanonicalMap, canonical_map_id)
            if record is None:
                raise HTTPException(status_code=404, detail="map not found")
            return await _map_payload(
                session,
                record,
                detailed=True,
                live_state_max_age_seconds=live_state_max_age_seconds,
                live_market_max_age_seconds=live_market_max_age_seconds,
                market_max_pair_skew_seconds=market_max_pair_skew_seconds,
            )

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
                await websocket.send_json(jsonable_encoder(await runtime_payload()))
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


async def _map_summary_payloads(
    session: AsyncSession,
    maps: list[CanonicalMap],
    *,
    live_state_max_age_seconds: float,
    live_market_max_age_seconds: float,
    market_max_pair_skew_seconds: float,
) -> list[dict]:
    if not maps:
        return []
    map_ids = [item.id for item in maps]
    series_ids = list({item.series_id for item in maps if item.series_id is not None})
    series_rows = list(
        (
            await session.scalars(select(CanonicalSeries).where(CanonicalSeries.id.in_(series_ids)))
        ).all()
    )
    series_by_id = {item.id: item for item in series_rows}
    team_ids = list(
        {team_id for series in series_rows for team_id in (series.team_a_id, series.team_b_id)}
    )
    teams = list(
        (await session.scalars(select(CanonicalTeam).where(CanonicalTeam.id.in_(team_ids)))).all()
    )
    team_by_id = {item.id: item for item in teams}

    event_ids = list({series.event_id for series in series_rows if series.event_id is not None})
    events = (
        list((await session.scalars(select(CanonicalEvent).where(CanonicalEvent.id.in_(event_ids)))).all())
        if event_ids
        else []
    )
    event_by_id = {item.id: item for item in events}

    # Query all maps across these series to know siblings and compute series scores
    all_series_maps = (
        list(
            (
                await session.scalars(
                    select(CanonicalMap)
                    .where(CanonicalMap.series_id.in_(series_ids))
                    .order_by(CanonicalMap.map_number.asc().nulls_last())
                )
            ).all()
        )
        if series_ids
        else []
    )
    all_map_ids = list({item.id for item in all_series_maps} | set(map_ids))
    all_results = (
        list(
            (
                await session.scalars(
                    select(MapResultRecord).where(MapResultRecord.canonical_map_id.in_(all_map_ids))
                )
            ).all()
        )
        if all_map_ids
        else []
    )
    result_by_map_id = {item.canonical_map_id: item for item in all_results}

    series_scores: dict[UUID, dict[str, int]] = {s.id: {"team_a": 0, "team_b": 0} for s in series_rows}
    maps_by_series: dict[UUID, list[CanonicalMap]] = {}
    for sm in all_series_maps:
        if sm.series_id is not None:
            maps_by_series.setdefault(sm.series_id, []).append(sm)
            res = result_by_map_id.get(sm.id)
            if res is not None and res.winner_team_id is not None:
                s = series_by_id.get(sm.series_id)
                if s is not None:
                    if res.winner_team_id == s.team_a_id:
                        series_scores[s.id]["team_a"] += 1
                    elif res.winner_team_id == s.team_b_id:
                        series_scores[s.id]["team_b"] += 1

    mappings = list(
        (
            await session.scalars(
                select(ProviderMatchMapping).where(
                    ProviderMatchMapping.provider == "raybet",
                    ProviderMatchMapping.canonical_series_id.in_(series_ids),
                )
            )
        ).all()
    )
    provider_match_by_series = {
        item.canonical_series_id: int(item.provider_match_id)
        for item in mappings
        if item.canonical_series_id is not None
    }
    provider_match_ids = list(set(provider_match_by_series.values()))
    latest_raybet_times = (
        select(
            RayBetMatch.provider_match_id,
            func.max(RayBetMatch.observed_at).label("latest_observed_at"),
        )
        .where(RayBetMatch.provider_match_id.in_(provider_match_ids))
        .group_by(RayBetMatch.provider_match_id)
        .subquery()
    )
    raybet_matches = list(
        (
            await session.scalars(
                select(RayBetMatch).join(
                    latest_raybet_times,
                    and_(
                        RayBetMatch.provider_match_id == latest_raybet_times.c.provider_match_id,
                        RayBetMatch.observed_at == latest_raybet_times.c.latest_observed_at,
                    ),
                )
            )
        ).all()
    )
    raybet_by_id = {item.provider_match_id: item for item in raybet_matches}

    latest_market_times = (
        select(
            OddsObservationRecord.odds_id,
            func.max(OddsObservationRecord.received_at).label("latest_received_at"),
        )
        .where(
            OddsObservationRecord.market_type == "Winner",
            or_(
                OddsObservationRecord.canonical_map_id.in_(map_ids),
                OddsObservationRecord.canonical_series_id.in_(series_ids),
            ),
        )
        .group_by(OddsObservationRecord.odds_id)
        .subquery()
    )
    market_rows = list(
        (
            await session.scalars(
                select(OddsObservationRecord).join(
                    latest_market_times,
                    and_(
                        OddsObservationRecord.odds_id == latest_market_times.c.odds_id,
                        OddsObservationRecord.received_at
                        == latest_market_times.c.latest_received_at,
                    ),
                )
            )
        ).all()
    )
    latest_live_times = (
        select(
            DltvLiveObservationRecord.canonical_map_id,
            func.max(DltvLiveObservationRecord.received_at).label("latest_received_at"),
        )
        .where(DltvLiveObservationRecord.canonical_map_id.in_(map_ids))
        .group_by(DltvLiveObservationRecord.canonical_map_id)
        .subquery()
    )
    live_rows = list(
        (
            await session.scalars(
                select(DltvLiveObservationRecord).join(
                    latest_live_times,
                    and_(
                        DltvLiveObservationRecord.canonical_map_id
                        == latest_live_times.c.canonical_map_id,
                        DltvLiveObservationRecord.received_at
                        == latest_live_times.c.latest_received_at,
                    ),
                )
            )
        ).all()
    )
    live_by_map = {item.canonical_map_id: item for item in live_rows}
    latest_snapshot_times = (
        select(
            DecisionSnapshotRecord.canonical_map_id,
            func.max(DecisionSnapshotRecord.decision_at).label("latest_decision_at"),
        )
        .where(DecisionSnapshotRecord.canonical_map_id.in_(map_ids))
        .group_by(DecisionSnapshotRecord.canonical_map_id)
        .subquery()
    )
    snapshots = list(
        (
            await session.scalars(
                select(DecisionSnapshotRecord).join(
                    latest_snapshot_times,
                    and_(
                        DecisionSnapshotRecord.canonical_map_id
                        == latest_snapshot_times.c.canonical_map_id,
                        DecisionSnapshotRecord.decision_at
                        == latest_snapshot_times.c.latest_decision_at,
                    ),
                )
            )
        ).all()
    )
    snapshot_by_map = {item.canonical_map_id: item for item in snapshots}
    results = list(
        (
            await session.scalars(
                select(MapResultRecord).where(MapResultRecord.canonical_map_id.in_(map_ids))
            )
        ).all()
    )
    result_by_map = {item.canonical_map_id: item for item in results}
    observed_at = datetime.now(UTC)
    payloads: list[dict] = []
    for canonical_map in maps:
        series = series_by_id.get(canonical_map.series_id)
        team_a = team_by_id.get(series.team_a_id) if series is not None else None
        team_b = team_by_id.get(series.team_b_id) if series is not None else None
        event = event_by_id.get(series.event_id) if series is not None and series.event_id is not None else None
        provider_match_id = provider_match_by_series.get(canonical_map.series_id)
        raybet_match = raybet_by_id.get(provider_match_id)
        stages = set(
            _map_market_stages(
                canonical_map.map_number,
                best_of=series.best_of if series is not None else None,
            )
        )
        current_market = [
            item
            for item in market_rows
            if item.match_stage in stages
            and (
                item.canonical_map_id == canonical_map.id
                or item.canonical_series_id == canonical_map.series_id
            )
        ]
        team_order = {
            team_id: index
            for index, team_id in enumerate(
                (series.team_a_id, series.team_b_id) if series is not None else ()
            )
        }
        current_market.sort(
            key=lambda item: (team_order.get(item.selection_team_id, 2), item.odds_id)
        )
        live = live_by_map.get(canonical_map.id)
        snapshot = snapshot_by_map.get(canonical_map.id)
        result = result_by_map.get(canonical_map.id)
        scheduled_at = (
            canonical_map.scheduled_at
            or (series.scheduled_at if series is not None else None)
            or (raybet_match.scheduled_at if raybet_match is not None else None)
        )
        snapshot_market = snapshot.canonical_payload.get("market", {}) if snapshot else {}
        snapshot_quality = snapshot.canonical_payload.get("quality", {}) if snapshot else {}
        current_market_view, selected_legs = _current_market_payload(
            current_market,
            series=series,
            canonical_map_id=canonical_map.id,
            observed_at=observed_at,
            live_market_max_age_seconds=live_market_max_age_seconds,
            market_max_pair_skew_seconds=market_max_pair_skew_seconds,
        )
        display_market = list(selected_legs) if selected_legs is not None else current_market
        s_maps = maps_by_series.get(canonical_map.series_id, [canonical_map]) if canonical_map.series_id else [canonical_map]
        s_score = series_scores.get(canonical_map.series_id, {"team_a": 0, "team_b": 0}) if canonical_map.series_id else {"team_a": 0, "team_b": 0}
        payloads.append(
            {
                "entity_type": "MAP",
                "identity_status": "RESOLVED",
                "id": canonical_map.id,
                "series_id": canonical_map.series_id,
                "canonical_map_id": canonical_map.id,
                "map_number": canonical_map.map_number,
                "valve_match_id": canonical_map.valve_match_id,
                "best_of": series.best_of if series else None,
                "series_score": s_score,
                "series_maps": [
                    {
                        "canonical_map_id": str(m.id),
                        "map_number": m.map_number,
                        "valve_match_id": m.valve_match_id,
                        "winner_team_id": str(result_by_map_id[m.id].winner_team_id) if m.id in result_by_map_id and result_by_map_id[m.id].winner_team_id else None,
                    }
                    for m in s_maps
                ],
                "scheduled_at": scheduled_at,
                "phase": _match_phase(
                    scheduled_at=scheduled_at,
                    live=live,
                    result=result,
                    observed_at=observed_at,
                    live_state_max_age_seconds=live_state_max_age_seconds,
                ),
                "provider_match_id": provider_match_id,
                "tournament_name": raybet_match.tournament_name if raybet_match else (event.name if event else None),
                "round": raybet_match.round if raybet_match else (f"BO{series.best_of}" if series and series.best_of else None),
                "raw_status": raybet_match.raw_status if raybet_match else None,
                "provider_observed_at": raybet_match.observed_at if raybet_match else None,
                "team_a": {"id": team_a.id, "name": team_a.name} if team_a else None,
                "team_b": {"id": team_b.id, "name": team_b.name} if team_b else None,
                "market": [
                    _market_payload(item, observed_at=observed_at) for item in display_market
                ],
                "market_quality": (
                    current_market_view.get("quality") if current_market_view is not None else None
                ),
                "current_market_view": current_market_view,
                "snapshot_market_quality": (
                    snapshot_market.get("quality") if isinstance(snapshot_market, dict) else None
                ),
                "draft": None,
                "live": _live_payload(live, observed_at=observed_at),
                "sync": None,
                "latest_snapshot": _snapshot_payload(snapshot, snapshot_quality, snapshot_market),
                "decisions": [],
                "historical_prewarm": None,
            }
        )
    return payloads


def _market_pair_leg(record: OddsObservationRecord) -> MarketPairLeg:
    return MarketPairLeg(
        provider_match_id=record.provider_match_id,
        odds_id=record.odds_id,
        canonical_series_id=record.canonical_series_id,
        canonical_map_id=record.canonical_map_id,
        market_type=record.market_type,
        match_stage=record.match_stage,
        selection_team_id=record.selection_team_id,
        price=record.price,
        normalized_status=record.normalized_status,
        metadata_version=record.metadata_version,
        received_at=record.received_at,
    )


def _current_market_evaluation(
    rows: Sequence[OddsObservationRecord],
    *,
    series: CanonicalSeries | None,
    canonical_map_id: UUID | None,
    observed_at: datetime,
    live_market_max_age_seconds: float,
    market_max_pair_skew_seconds: float,
) -> tuple[tuple[OddsObservationRecord, OddsObservationRecord], MarketPairQuality] | None:
    """Pick and evaluate the freshest complete A/B market pair.

    Mirrors the snapshot builder's pairing rules: candidate legs are grouped
    by (provider match, market type, match stage) and the freshest pair wins.
    """
    if series is None or series.team_a_id is None or series.team_b_id is None:
        return None
    team_ids = frozenset({series.team_a_id, series.team_b_id})
    latest_by_odds: dict[int, OddsObservationRecord] = {}
    for row in rows:
        current = latest_by_odds.get(row.odds_id)
        if current is None or row.received_at > current.received_at:
            latest_by_odds[row.odds_id] = row
    grouped: dict[tuple[int, str | None, str | None], dict[UUID, OddsObservationRecord]] = {}
    for row in latest_by_odds.values():
        if row.selection_team_id not in team_ids:
            continue
        grouped.setdefault((row.provider_match_id, row.market_type, row.match_stage), {})[
            row.selection_team_id
        ] = row
    evaluated: list[
        tuple[float, tuple[OddsObservationRecord, OddsObservationRecord], MarketPairQuality]
    ] = []
    for (_provider_match_id, _market_type, match_stage), by_team in grouped.items():
        if set(by_team) != team_ids:
            continue
        legs = (
            by_team[series.team_a_id],
            by_team[series.team_b_id],
        )
        quality = evaluate_market_pair(
            tuple(_market_pair_leg(record) for record in legs),
            expected_series_id=series.id,
            # The deciding-map fallback uses the series-scoped "final" market
            # whose observations carry no map identity; map checks are skipped
            # for that stage by design.
            expected_map_id=None if match_stage == "final" else canonical_map_id,
            expected_team_ids=team_ids,
            decision_at=observed_at,
            max_age_seconds=live_market_max_age_seconds,
            max_pair_skew_seconds=market_max_pair_skew_seconds,
        )
        freshness = max(legs[0].received_at, legs[1].received_at)
        evaluated.append((freshness, legs, quality))
    if not evaluated:
        return None
    # Prefer an eligible pair (open, fresh) over a stale/suspended candidate;
    # this is what lets the live "final" market of a deciding map replace the
    # delisted per-map r{n} market.
    eligible = [candidate for candidate in evaluated if candidate[2].eligible]
    _, legs, quality = max(eligible or evaluated, key=lambda item: item[0])
    return legs, quality


def _current_market_payload(
    rows: Sequence[OddsObservationRecord],
    *,
    series: CanonicalSeries | None,
    canonical_map_id: UUID | None,
    observed_at: datetime,
    live_market_max_age_seconds: float,
    market_max_pair_skew_seconds: float,
) -> tuple[dict | None, tuple[OddsObservationRecord, OddsObservationRecord] | None]:
    """Derived current-market view plus the selected pair legs.

    The view carries raw observations with vig-removed fair probabilities
    evaluated live at request time; the legs are the canonical pair the UI
    should display.  Raw Observation (market list) != Derived Current Market
    (this block) != Frozen Snapshot Market (snapshot_market_quality /
    latest_snapshot.market).
    """
    evaluated = _current_market_evaluation(
        rows,
        series=series,
        canonical_map_id=canonical_map_id,
        observed_at=observed_at,
        live_market_max_age_seconds=live_market_max_age_seconds,
        market_max_pair_skew_seconds=market_max_pair_skew_seconds,
    )
    if evaluated is None:
        return None, None
    legs, quality = evaluated
    fair_a = fair_b = None
    overround = None
    if quality.eligible:
        fair_a, fair_b, implied_total = remove_vig(float(legs[0].price), float(legs[1].price))
        overround = implied_total - 1.0
    return (
        {
            "team_a": _current_market_leg(legs[0], fair_a),
            "team_b": _current_market_leg(legs[1], fair_b),
            "overround": overround,
            "quality": quality.model_dump(mode="json"),
        },
        legs,
    )


def _current_market_leg(record: OddsObservationRecord, fair_probability: float | None) -> dict:
    implied = record.implied_probability
    if implied is None:
        try:
            implied = 1.0 / float(record.price)
        except TypeError, ValueError, ZeroDivisionError:
            implied = None
    return {
        "odds_id": record.odds_id,
        "selection_team_id": (
            str(record.selection_team_id) if record.selection_team_id is not None else None
        ),
        "price": record.price,
        "implied_probability": implied,
        "fair_probability": fair_probability,
    }


def _market_payload(item: OddsObservationRecord, *, observed_at: datetime) -> dict:
    return {
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


def _live_payload(
    live: DltvLiveObservationRecord | None,
    *,
    observed_at: datetime,
) -> dict | None:
    if live is None:
        return None
    return {
        "game_time_seconds": live.game_time_seconds,
        "radiant_kills": live.radiant_kills,
        "dire_kills": live.dire_kills,
        "radiant_nw_lead": live.radiant_nw_lead,
        "first_blood": live.first_blood,
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


def _snapshot_payload(
    snapshot: DecisionSnapshotRecord | None,
    quality: dict,
    market: dict,
) -> dict | None:
    if snapshot is None:
        return None
    history = snapshot.canonical_payload.get("history", {})
    return {
        "id": snapshot.id,
        "decision_at": snapshot.decision_at,
        "created_at": snapshot.created_at,
        "mode": snapshot.mode,
        "snapshot_hash": snapshot.snapshot_hash,
        "quality": quality,
        "market_quality": market.get("quality") if isinstance(market, dict) else None,
        "history_coverage": history.get("coverage") if isinstance(history, dict) else None,
    }


async def _map_payload(
    session: AsyncSession,
    canonical_map: CanonicalMap,
    *,
    detailed: bool = False,
    live_state_max_age_seconds: float = 45.0,
    live_market_max_age_seconds: float = 30.0,
    market_max_pair_skew_seconds: float = 5.0,
) -> dict:
    series = (
        await session.get(CanonicalSeries, canonical_map.series_id)
        if canonical_map.series_id is not None
        else None
    )
    team_a = await session.get(CanonicalTeam, series.team_a_id) if series else None
    team_b = await session.get(CanonicalTeam, series.team_b_id) if series else None
    event = (
        await session.get(CanonicalEvent, series.event_id)
        if series and series.event_id is not None
        else None
    )
    sibling_maps = (
        list(
            (
                await session.scalars(
                    select(CanonicalMap)
                    .where(CanonicalMap.series_id == canonical_map.series_id)
                    .order_by(CanonicalMap.map_number.asc().nulls_last())
                )
            ).all()
        )
        if canonical_map.series_id
        else [canonical_map]
    )
    sibling_map_ids = [m.id for m in sibling_maps]
    sibling_results = (
        list(
            (
                await session.scalars(
                    select(MapResultRecord).where(MapResultRecord.canonical_map_id.in_(sibling_map_ids))
                )
            ).all()
        )
        if sibling_map_ids
        else []
    )
    sibling_result_by_id = {item.canonical_map_id: item for item in sibling_results}
    s_score = {"team_a": 0, "team_b": 0}
    if series:
        for res in sibling_results:
            if res.winner_team_id == series.team_a_id:
                s_score["team_a"] += 1
            elif res.winner_team_id == series.team_b_id:
                s_score["team_b"] += 1
    raybet_match = await _latest_raybet_match(session, canonical_map.series_id)
    market_criteria = (
        or_(
            OddsObservationRecord.canonical_map_id == canonical_map.id,
            OddsObservationRecord.canonical_series_id == canonical_map.series_id,
        ),
        OddsObservationRecord.market_type == "Winner",
        OddsObservationRecord.match_stage.in_(
            _map_market_stages(
                canonical_map.map_number,
                best_of=series.best_of if series is not None else None,
            )
        ),
    )
    latest_market_times = (
        select(
            OddsObservationRecord.odds_id,
            func.max(OddsObservationRecord.received_at).label("latest_received_at"),
        )
        .where(*market_criteria)
        .group_by(OddsObservationRecord.odds_id)
        .subquery()
    )
    odds = list(
        (
            await session.scalars(
                select(OddsObservationRecord).join(
                    latest_market_times,
                    and_(
                        OddsObservationRecord.odds_id == latest_market_times.c.odds_id,
                        OddsObservationRecord.received_at
                        == latest_market_times.c.latest_received_at,
                    ),
                )
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
    market_timeline_rows = list(
        (
            await session.scalars(
                select(OddsObservationRecord)
                .where(*market_criteria)
                .order_by(OddsObservationRecord.received_at.desc())
                .limit(300)
            )
        ).all()
    )
    draft = (
        await session.scalar(
            select(DraftSnapshotRecord)
            .where(DraftSnapshotRecord.canonical_map_id == canonical_map.id)
            .order_by(DraftSnapshotRecord.observed_at.desc())
            .limit(1)
        )
        if canonical_map.valve_match_id is not None
        else None
    )
    draft_slots = (
        list(
            (
                await session.scalars(
                    select(DraftSlotRecord)
                    .where(DraftSlotRecord.draft_snapshot_id == draft.id)
                    .order_by(DraftSlotRecord.side, DraftSlotRecord.position)
                )
            ).all()
        )
        if draft is not None
        else []
    )
    player_form_ready_count = 0
    player_hero_ready_count = 0
    player_feature_cutoffs: list[datetime] = []
    historical = HistoricalIntelligenceService()
    history_as_of = datetime.now(UTC)
    team_a_history = (
        await historical.get_team_payload(session, series.team_a_id, as_of=history_as_of)
        if series is not None
        else None
    )
    team_b_history = (
        await historical.get_team_payload(session, series.team_b_id, as_of=history_as_of)
        if series is not None
        else None
    )
    team_histories = (
        (team_a_history, team_b_history)
        if team_a_history is not None and team_b_history is not None
        else ()
    )
    team_strength_ready_count = sum(
        item.get("rating") is not None
        for item in (team_a_history, team_b_history)
        if series is not None
    )
    for team_history in team_histories:
        if team_history["knowledge_cutoff"] is not None:
            player_feature_cutoffs.append(team_history["knowledge_cutoff"])
    for slot in draft_slots:
        if slot.canonical_player_id is None:
            continue
        player_form = await session.scalar(
            select(PlayerFormSnapshotRecord)
            .where(
                PlayerFormSnapshotRecord.canonical_player_id == slot.canonical_player_id,
                PlayerFormSnapshotRecord.position == slot.position,
            )
            .order_by(PlayerFormSnapshotRecord.knowledge_cutoff.desc())
            .limit(1)
        )
        if player_form is not None:
            player_form_ready_count += 1
            player_feature_cutoffs.append(player_form.knowledge_cutoff)
        if slot.hero_id is None:
            continue
        player_hero = await session.scalar(
            select(PlayerHeroSnapshotRecord)
            .where(
                PlayerHeroSnapshotRecord.canonical_player_id == slot.canonical_player_id,
                PlayerHeroSnapshotRecord.hero_id == slot.hero_id,
                PlayerHeroSnapshotRecord.position == slot.position,
            )
            .order_by(PlayerHeroSnapshotRecord.knowledge_cutoff.desc())
            .limit(1)
        )
        if player_hero is not None:
            player_hero_ready_count += 1
            player_feature_cutoffs.append(player_hero.knowledge_cutoff)
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
    checkpoint_snapshots = list(
        (
            await session.scalars(
                select(DecisionSnapshotRecord)
                .where(DecisionSnapshotRecord.canonical_map_id == canonical_map.id)
                .order_by(DecisionSnapshotRecord.decision_at.desc())
                .limit(5)
            )
        ).all()
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
    checkpoint_decisions: list[AiDecisionRecord] = []
    snapshot_by_id = {item.id: item for item in checkpoint_snapshots}
    if detailed and snapshot_by_id:
        checkpoint_decisions = list(
            (
                await session.scalars(
                    select(AiDecisionRecord).where(AiDecisionRecord.snapshot_id.in_(snapshot_by_id))
                )
            ).all()
        )
    future_odds = []
    result = await session.scalar(
        select(MapResultRecord).where(MapResultRecord.canonical_map_id == canonical_map.id)
    )
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
    scheduled_at = (
        canonical_map.scheduled_at
        or (series.scheduled_at if series is not None else None)
        or (raybet_match.scheduled_at if raybet_match is not None else None)
    )
    phase = _match_phase(
        scheduled_at=scheduled_at,
        live=live,
        result=result,
        observed_at=observed_at,
        live_state_max_age_seconds=live_state_max_age_seconds,
    )
    current_market_view, selected_legs = _current_market_payload(
        current_market,
        series=series,
        canonical_map_id=canonical_map.id,
        observed_at=observed_at,
        live_market_max_age_seconds=live_market_max_age_seconds,
        market_max_pair_skew_seconds=market_max_pair_skew_seconds,
    )
    display_market = list(selected_legs) if selected_legs is not None else current_market
    payload = {
        "entity_type": "MAP",
        "identity_status": "RESOLVED",
        "id": canonical_map.id,
        "series_id": canonical_map.series_id,
        "canonical_map_id": canonical_map.id,
        "map_number": canonical_map.map_number,
        "valve_match_id": canonical_map.valve_match_id,
        "best_of": series.best_of if series else None,
        "series_score": s_score,
        "series_maps": [
            {
                "canonical_map_id": str(m.id),
                "map_number": m.map_number,
                "valve_match_id": m.valve_match_id,
                "winner_team_id": str(sibling_result_by_id[m.id].winner_team_id) if m.id in sibling_result_by_id and sibling_result_by_id[m.id].winner_team_id else None,
            }
            for m in sibling_maps
        ],
        "scheduled_at": scheduled_at,
        "phase": phase,
        "provider_match_id": raybet_match.provider_match_id if raybet_match else None,
        "tournament_name": raybet_match.tournament_name if raybet_match else (event.name if event else None),
        "round": raybet_match.round if raybet_match else (f"BO{series.best_of}" if series and series.best_of else None),
        "raw_status": raybet_match.raw_status if raybet_match else None,
        "provider_observed_at": raybet_match.observed_at if raybet_match else None,
        "team_a": {"id": team_a.id, "name": team_a.name} if team_a else None,
        "team_b": {"id": team_b.id, "name": team_b.name} if team_b else None,
        "market": [_market_payload(item, observed_at=observed_at) for item in display_market],
        "market_quality": (
            current_market_view.get("quality") if current_market_view is not None else None
        ),
        "current_market_view": current_market_view,
        "snapshot_market_quality": (
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
                "roster_ready_count": sum(slot.account_id is not None for slot in draft_slots),
                "hero_ready_count": sum(slot.hero_id is not None for slot in draft_slots),
                "slots": [await _draft_slot_payload(session, slot) for slot in draft_slots],
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
                "first_blood": live.first_blood,
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
        "historical_prewarm": {
            "team_strength_ready_count": sum(
                item["base_rating"] is not None for item in team_histories
            ),
            "player_form_ready_count": player_form_ready_count,
            "player_hero_ready_count": player_hero_ready_count,
            "latest_knowledge_cutoff": max(player_feature_cutoffs)
            if player_feature_cutoffs
            else None,
        },
    }
    if detailed and snapshot is not None:
        payload["snapshot_payload"] = snapshot.canonical_payload
        payload["future_odds"] = [_future_odds_payload(item) for item in future_odds]
    elif detailed:
        payload["future_odds"] = []
    if detailed:
        payload["checkpoint_decisions"] = [
            _decision_payload(item)
            | {
                "snapshot_decision_at": snapshot_by_id[item.snapshot_id].decision_at,
                "snapshot_mode": snapshot_by_id[item.snapshot_id].mode,
            }
            for item in sorted(
                checkpoint_decisions,
                key=lambda record: (
                    snapshot_by_id[record.snapshot_id].decision_at,
                    record.provider,
                ),
                reverse=True,
            )
        ]
        payload["market_timeline"] = [
            _market_payload(item, observed_at=observed_at)
            for item in reversed(market_timeline_rows)
        ]
        payload["live_timeline"] = [
            {
                "game_time_seconds": item.game_time_seconds,
                "radiant_kills": item.radiant_kills,
                "dire_kills": item.dire_kills,
                "radiant_nw_lead": item.radiant_nw_lead,
                "first_blood": item.first_blood,
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


def _match_phase(
    *,
    scheduled_at: datetime | None,
    live: DltvLiveObservationRecord | None,
    result: MapResultRecord | None,
    observed_at: datetime,
    live_state_max_age_seconds: float,
) -> str:
    if result is not None:
        return "POSTMATCH"
    if live is not None:
        message_age = elapsed_seconds(observed_at, live.last_message_received_at)
        if 0 <= message_age <= live_state_max_age_seconds:
            return "LIVE"
        return "AWAITING_RESULT"
    if scheduled_at is not None and ensure_utc(scheduled_at) >= ensure_utc(observed_at):
        return "PREMATCH"
    return "UNKNOWN"


async def _draft_slot_payload(session: AsyncSession, slot: DraftSlotRecord) -> dict:
    player = (
        await session.get(CanonicalPlayer, slot.canonical_player_id)
        if slot.canonical_player_id is not None
        else None
    )
    hero = await session.get(CanonicalHero, slot.hero_id) if slot.hero_id is not None else None
    return {
        "side": slot.side,
        "position": slot.position,
        "account_id": slot.account_id,
        "canonical_player_id": str(slot.canonical_player_id)
        if slot.canonical_player_id is not None
        else None,
        "player_name": player.name if player is not None else None,
        "hero_id": slot.hero_id,
        "hero_name": hero.name if hero is not None else None,
    }


async def _pending_series_payload(
    session: AsyncSession,
    series: CanonicalSeries,
    *,
    live_market_max_age_seconds: float,
    market_max_pair_skew_seconds: float,
) -> dict | None:
    raybet_match = await _latest_raybet_match(session, series.id)
    team_a = await session.get(CanonicalTeam, series.team_a_id)
    team_b = await session.get(CanonicalTeam, series.team_b_id)
    event = await session.get(CanonicalEvent, series.event_id) if series.event_id else None
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
        team_id: index for index, team_id in enumerate((series.team_a_id, series.team_b_id))
    }
    current_market = sorted(
        _series_market_rows(latest_odds.values()),
        key=lambda item: (team_order.get(item.selection_team_id, 2), item.odds_id),
    )
    snapshot = await session.scalar(
        select(DecisionSnapshotRecord)
        .where(
            DecisionSnapshotRecord.canonical_map_id.is_(None),
            DecisionSnapshotRecord.canonical_payload["identity"]["series_id"].as_string()
            == str(series.id),
        )
        .order_by(DecisionSnapshotRecord.decision_at.desc())
        .limit(1)
    )
    snapshot_history = snapshot.canonical_payload.get("history", {}) if snapshot else {}
    snapshot_market = snapshot.canonical_payload.get("market", {}) if snapshot else {}
    snapshot_quality = snapshot.canonical_payload.get("quality", {}) if snapshot else {}
    historical = HistoricalIntelligenceService()
    history_as_of = datetime.now(UTC)
    team_a_history = await historical.get_team_payload(
        session, series.team_a_id, as_of=history_as_of
    )
    team_b_history = await historical.get_team_payload(
        session, series.team_b_id, as_of=history_as_of
    )
    history_cutoffs = [
        item["knowledge_cutoff"]
        for item in (team_a_history, team_b_history)
        if item["knowledge_cutoff"] is not None
    ]
    observed_at = datetime.now(UTC)
    scheduled_at = series.scheduled_at or (raybet_match.scheduled_at if raybet_match else None)
    current_market_view, selected_legs = _current_market_payload(
        current_market,
        series=series,
        canonical_map_id=None,
        observed_at=observed_at,
        live_market_max_age_seconds=live_market_max_age_seconds,
        market_max_pair_skew_seconds=market_max_pair_skew_seconds,
    )
    display_market = list(selected_legs) if selected_legs is not None else current_market
    return {
        "entity_type": "SERIES",
        "identity_status": "PENDING_MAP_IDENTITY",
        "id": series.id,
        "series_id": series.id,
        "canonical_map_id": None,
        "map_number": None,
        "valve_match_id": None,
        "best_of": series.best_of,
        "series_score": {"team_a": 0, "team_b": 0},
        "series_maps": [],
        "scheduled_at": scheduled_at,
        "phase": (
            "PREMATCH"
            if scheduled_at is not None and ensure_utc(scheduled_at) >= ensure_utc(observed_at)
            else "UNKNOWN"
        ),
        "provider_match_id": raybet_match.provider_match_id if raybet_match else None,
        "tournament_name": raybet_match.tournament_name if raybet_match else (event.name if event else None),
        "round": raybet_match.round if raybet_match else (f"BO{series.best_of}" if series.best_of else None),
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
            for item in display_market
        ],
        "market_quality": (
            current_market_view.get("quality") if current_market_view is not None else None
        ),
        "current_market_view": current_market_view,
        "snapshot_market_quality": (
            snapshot_market.get("quality") if isinstance(snapshot_market, dict) else None
        ),
        "draft": None,
        "live": None,
        "sync": None,
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
                "history_coverage": (
                    snapshot_history.get("coverage") if isinstance(snapshot_history, dict) else None
                ),
            }
            if snapshot
            else None
        ),
        "decisions": [],
        "historical_prewarm": {
            "team_strength_ready_count": sum(
                item.get("base_rating") is not None for item in (team_a_history, team_b_history) if item
            ),
            "player_form_ready_count": 0,
            "player_hero_ready_count": 0,
            "latest_knowledge_cutoff": max(history_cutoffs) if history_cutoffs else None,
        },
    }


async def _latest_raybet_match(session: AsyncSession, series_id: UUID | None) -> RayBetMatch | None:
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


def _map_market_stages(map_number: int | None, *, best_of: int | None = None) -> tuple[str, ...]:
    if map_number is None:
        return ()
    stages = (
        f"r{map_number}",
        f"Map r{map_number}",
        f"map r{map_number}",
        f"Map {map_number}",
        f"map {map_number}",
    )
    if best_of is not None and map_number == best_of:
        # RayBet withdraws the per-map winner market of the DECIDING map (the
        # r{n} odds stop updating and are delisted, status 4) and keeps only
        # the series winner ("final") market live; for the deciding map that
        # market IS the map winner, so it must be a candidate stage.
        stages += ("final",)
    return stages


def _series_market_rows(rows):
    return list(rows)


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
