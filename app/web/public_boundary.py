import json

from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request


class PublicMatchDataBoundaryMiddleware(BaseHTTPMiddleware):
    """Remove premium AI payloads from endpoints that are intentionally public.

    The existing projection builder still owns the canonical match shape. This
    middleware is the transport boundary: public match endpoints never emit AI
    decisions, checkpoint history, frozen AI input payloads, or decision-linked
    future-odds captures. Paid clients fetch those from the dedicated premium
    endpoint instead.
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
    sanitized = dict(payload)
    decisions = sanitized.get("decisions")
    decision_rows = decisions if isinstance(decisions, list) else []
    completed_models = len(
        {
            (item.get("provider"), item.get("model"))
            for item in decision_rows
            if isinstance(item, dict) and item.get("provider") and item.get("model")
        }
    )
    snapshot = sanitized.get("latest_snapshot")
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

    sanitized["ai_access"] = {
        "required_entitlement": "ai_decisions",
        "analysis_available": snapshot_summary is not None,
        "updated_at": snapshot_summary.get("decision_at") if snapshot_summary else None,
        "completed_models": completed_models,
    }
    sanitized["latest_snapshot"] = snapshot_summary
    sanitized["decisions"] = []
    sanitized.pop("checkpoint_decisions", None)
    sanitized.pop("snapshot_payload", None)
    sanitized.pop("future_odds", None)
    return sanitized
