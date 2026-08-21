from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import load_only

from app.access_policy import resolve_map_access
from app.auth import AuthenticatedUser
from app.entitlements import EntitlementService
from app.models import (
    AiDecisionRecord,
    CanonicalMap,
    DecisionEvaluationRecord,
    DecisionFutureOdds,
    DecisionSnapshotRecord,
)
from app.web.api import _canonical_decision_rounds, _decision_payload, _future_odds_payload
from app.web.performance import build_ai_performance_payload


def create_premium_router(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    live_state_max_age_seconds: float,
    live_market_max_age_seconds: float,
    market_max_pair_skew_seconds: float,
) -> APIRouter:
    router = APIRouter()
    entitlements = EntitlementService(session_factory)

    @router.get("/api/maps/{canonical_map_id}/ai-decisions")
    async def map_ai_decisions(canonical_map_id: UUID, request: Request) -> dict:
        user = _optional_request_user(request)
        async with session_factory() as session:
            access = await resolve_map_access(
                session,
                entitlements,
                canonical_map_id,
                user=user,
            )
            if access is None:
                raise HTTPException(status_code=404, detail="map not found")
            if not access.ai_allowed:
                if user is None:
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="authentication required",
                    )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="AI Decision access is not granted for this match",
                )
            return await _map_ai_decisions_payload(
                session,
                access.canonical_map,
                public=access.ai_public_projection,
            )

    @router.get("/api/ai-performance")
    async def ai_performance(
        request: Request,
        limit: int = Query(default=1000, ge=1, le=1000),
        offset: int = Query(default=0, ge=0, le=100_000),
    ) -> dict:
        """Cross-match experiment analytics are part of Free Access."""

        async with session_factory() as session:
            return await build_ai_performance_payload(session, limit=limit, offset=offset)

    return router


async def _map_ai_decisions_payload(
    session: AsyncSession,
    canonical_map: CanonicalMap,
    *,
    public: bool = False,
) -> dict:
    snapshots = list(
        (
            await session.scalars(
                select(DecisionSnapshotRecord)
                .options(
                    load_only(
                        DecisionSnapshotRecord.id,
                        DecisionSnapshotRecord.canonical_map_id,
                        DecisionSnapshotRecord.decision_at,
                        DecisionSnapshotRecord.created_at,
                        DecisionSnapshotRecord.mode,
                        DecisionSnapshotRecord.canonical_payload,
                        DecisionSnapshotRecord.snapshot_hash,
                    )
                )
                .where(DecisionSnapshotRecord.canonical_map_id == canonical_map.id)
                .order_by(DecisionSnapshotRecord.decision_at.desc())
                .limit(200)
            )
        ).all()
    )
    if not snapshots:
        return {
            "canonical_map_id": str(canonical_map.id),
            "canonical_series_id": (
                str(canonical_map.series_id) if canonical_map.series_id is not None else None
            ),
            "latest_snapshot": None,
            "decisions": [],
            "checkpoint_decisions": [],
            "snapshot_payload": None,
            "future_odds": [],
        }

    snapshot_by_id = {item.id: item for item in snapshots}
    decision_rows = list(
        (
            await session.scalars(
                select(AiDecisionRecord)
                .options(
                    load_only(
                        AiDecisionRecord.id,
                        AiDecisionRecord.snapshot_id,
                        AiDecisionRecord.snapshot_hash,
                        AiDecisionRecord.provider,
                        AiDecisionRecord.model,
                        AiDecisionRecord.model_version,
                        AiDecisionRecord.prompt_version,
                        AiDecisionRecord.decision_policy_version,
                        AiDecisionRecord.ai_view_version,
                        AiDecisionRecord.execution_config_version,
                        AiDecisionRecord.bankroll_before,
                        AiDecisionRecord.stake,
                        AiDecisionRecord.job_enqueued_at,
                        AiDecisionRecord.job_claimed_at,
                        AiDecisionRecord.input_prepare_started_at,
                        AiDecisionRecord.input_prepare_completed_at,
                        AiDecisionRecord.request_started_at,
                        AiDecisionRecord.response_received_at,
                        AiDecisionRecord.latency_seconds,
                        AiDecisionRecord.input_tokens,
                        AiDecisionRecord.cached_input_tokens,
                        AiDecisionRecord.reasoning_tokens,
                        AiDecisionRecord.output_tokens,
                        AiDecisionRecord.total_tokens,
                        AiDecisionRecord.decision_persisted_at,
                        AiDecisionRecord.normalized_response,
                        AiDecisionRecord.parse_status,
                        AiDecisionRecord.error,
                    )
                )
                .where(AiDecisionRecord.snapshot_id.in_(snapshot_by_id))
            )
        ).all()
    )
    decisions = _canonical_decision_rounds(decision_rows)
    decision_ids = [item.id for item in decisions]
    evaluations = (
        list(
            (
                await session.scalars(
                    select(DecisionEvaluationRecord).where(
                        DecisionEvaluationRecord.ai_decision_id.in_(decision_ids)
                    )
                )
            ).all()
        )
        if decision_ids
        else []
    )
    evaluation_by_decision = {item.ai_decision_id: item for item in evaluations}
    latest_snapshot = snapshots[0]
    future_odds = list(
        (
            await session.scalars(
                select(DecisionFutureOdds)
                .where(DecisionFutureOdds.decision_snapshot_id == latest_snapshot.id)
                .order_by(DecisionFutureOdds.triggered_at)
            )
        ).all()
    )
    latest_payload = latest_snapshot.canonical_payload
    latest_market = latest_payload.get("market", {})
    latest_history = latest_payload.get("history", {})
    latest_decisions = [item for item in decisions if item.snapshot_id == latest_snapshot.id]
    payload = {
        "canonical_map_id": str(canonical_map.id),
        "canonical_series_id": (
            str(canonical_map.series_id) if canonical_map.series_id is not None else None
        ),
        "latest_snapshot": {
            "id": latest_snapshot.id,
            "decision_at": latest_snapshot.decision_at,
            "created_at": latest_snapshot.created_at,
            "mode": latest_snapshot.mode,
            "snapshot_hash": latest_snapshot.snapshot_hash,
            "quality": latest_payload.get("quality", {}),
            "market_quality": (
                latest_market.get("quality") if isinstance(latest_market, dict) else None
            ),
            "history_coverage": (
                latest_history.get("coverage") if isinstance(latest_history, dict) else None
            ),
        },
        "decisions": [
            _decision_payload(item, evaluation_by_decision.get(item.id))
            for item in latest_decisions
        ],
        "checkpoint_decisions": [
            _decision_payload(item, evaluation_by_decision.get(item.id))
            | {
                "snapshot_decision_at": snapshot_by_id[item.snapshot_id].decision_at,
                "snapshot_mode": snapshot_by_id[item.snapshot_id].mode,
            }
            for item in sorted(
                decisions,
                key=lambda item: (
                    snapshot_by_id[item.snapshot_id].decision_at,
                    item.provider,
                ),
                reverse=True,
            )
        ],
        "snapshot_payload": latest_payload,
        "future_odds": [_future_odds_payload(item) for item in future_odds],
    }
    return _public_ai_decisions_payload(payload) if public else payload


_PUBLIC_DECISION_FIELDS = (
    "id",
    "snapshot_id",
    "provider",
    "model",
    "model_version",
    "prompt_version",
    "decision_policy_version",
    "ai_view_version",
    "execution_config_version",
    "decision_persisted_at",
    "response_received_at",
    "parse_status",
    "decision",
    "evaluation",
    "snapshot_decision_at",
    "snapshot_mode",
)
_PUBLIC_SNAPSHOT_FIELDS = ("id", "decision_at", "created_at", "mode", "quality", "market_quality")
_PUBLIC_QUALITY_FIELDS = frozenset({"eligible", "blockers", "warnings"})
_PRIVATE_DECISION_FIELDS = frozenset(
    {
        "stake",
        "bankroll_before",
        "virtual_bankroll",
        "locked_balance",
        "cash_balance",
        "equity",
        "realized_pnl",
        "unsettled_stakes",
    }
)


def _public_ai_decisions_payload(payload: dict) -> dict:
    latest = payload.get("latest_snapshot")
    public_latest = None
    if isinstance(latest, dict):
        public_latest = {key: latest[key] for key in _PUBLIC_SNAPSHOT_FIELDS if key in latest}
        for key in ("quality", "market_quality"):
            value = public_latest.get(key)
            if isinstance(value, dict):
                public_latest[key] = {
                    field: value[field] for field in _PUBLIC_QUALITY_FIELDS if field in value
                }

    return {
        "canonical_map_id": payload["canonical_map_id"],
        "canonical_series_id": payload["canonical_series_id"],
        "latest_snapshot": public_latest,
        "decisions": [_public_decision_payload(item) for item in payload.get("decisions", [])],
        "checkpoint_decisions": [
            _public_decision_payload(item) for item in payload.get("checkpoint_decisions", [])
        ],
        "snapshot_payload": None,
        "future_odds": [],
    }


def _public_decision_payload(payload: dict) -> dict:
    public = {key: payload[key] for key in _PUBLIC_DECISION_FIELDS if key in payload}
    decision = public.get("decision")
    if isinstance(decision, dict):
        public["decision"] = {
            key: value for key, value in decision.items() if key not in _PRIVATE_DECISION_FIELDS
        }
    return public


def _optional_request_user(request: Request) -> AuthenticatedUser | None:
    user = getattr(request.state, "auth_user", None)
    if not isinstance(user, AuthenticatedUser):
        return None
    return user
