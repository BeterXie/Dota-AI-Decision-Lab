import json

from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request

_PUBLIC_MATCH_FIELDS = frozenset(
    {
        "entity_type",
        "identity_status",
        "phase",
        "id",
        "series_id",
        "canonical_map_id",
        "map_number",
        "valve_match_id",
        "best_of",
        "series_score",
        "series_maps",
        "scheduled_at",
        "provider_match_id",
        "tournament_name",
        "round",
        "raw_status",
        "provider_observed_at",
        "team_a",
        "team_b",
        "market",
        "market_quality",
        "current_market_view",
        "snapshot_market_quality",
        "draft",
        "live",
        "sync",
        "historical_prewarm",
        "market_timeline",
        "live_timeline",
        "result",
        "result_evidence",
    }
)


class PublicMatchDataBoundaryMiddleware(BaseHTTPMiddleware):
    """Build a fail-closed public projection for ordinary match endpoints.

    The canonical map builder may grow new fields over time. Public responses do
    not inherit those fields automatically: only the explicit allowlist below,
    plus a deliberately reduced AI-readiness summary, can cross this boundary.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        if (
            request.method != "GET"
            or response.status_code != 200
            or not _is_public_match_endpoint(request.url.path)
            or "application/json" not in response.headers.get("content-type", "")
        ):
            return response

        body = b"".join([chunk async for chunk in response.body_iterator])
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            return Response(
                content=body,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=response.media_type,
            )

        if isinstance(payload, list):
            sanitized = [
                _sanitize_match_payload(item) if isinstance(item, dict) else item
                for item in payload
            ]
        elif isinstance(payload, dict):
            sanitized = _sanitize_match_payload(payload)
        else:
            sanitized = payload

        headers = dict(response.headers)
        headers.pop("content-length", None)
        return JSONResponse(
            content=jsonable_encoder(sanitized),
            status_code=response.status_code,
            headers=headers,
        )


def _is_public_match_endpoint(path: str) -> bool:
    if path == "/api/matches":
        return True
    segments = [segment for segment in path.split("/") if segment]
    return len(segments) == 3 and segments[:2] == ["api", "maps"]


def _sanitize_match_payload(payload: dict) -> dict:
    decision_rows = payload.get("decisions")
    decisions = decision_rows if isinstance(decision_rows, list) else []
    completed_models = len(
        {
            (item.get("provider"), item.get("model"))
            for item in decisions
            if isinstance(item, dict) and item.get("provider") and item.get("model")
        }
    )

    snapshot = payload.get("latest_snapshot")
    snapshot_summary = None
    if isinstance(snapshot, dict):
        snapshot_summary = {
            key: snapshot.get(key)
            for key in (
                "id",
                "decision_at",
                "created_at",
                "mode",
                "market_quality",
                "history_coverage",
                "quality",
            )
            if key in snapshot
        }

    sanitized = {key: payload[key] for key in _PUBLIC_MATCH_FIELDS if key in payload}
    sanitized["latest_snapshot"] = snapshot_summary
    sanitized["decisions"] = []
    sanitized["ai_access"] = {
        "required_entitlement": "ai_decisions",
        "analysis_available": snapshot_summary is not None,
        "updated_at": snapshot_summary.get("decision_at") if snapshot_summary else None,
        "completed_models": completed_models,
    }
    return sanitized
