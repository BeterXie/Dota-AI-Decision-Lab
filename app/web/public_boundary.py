import json

from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request

_PUBLIC_MATCH_SCALAR_FIELDS = frozenset(
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
        "scheduled_at",
        "provider_match_id",
        "tournament_name",
        "round",
        "raw_status",
        "provider_observed_at",
    }
)
_TEAM_FIELDS = frozenset({"id", "name"})
_SERIES_SCORE_FIELDS = frozenset({"team_a", "team_b"})
_SERIES_MAP_FIELDS = frozenset(
    {"canonical_map_id", "map_number", "valve_match_id", "winner_team_id"}
)
_MARKET_FIELDS = frozenset(
    {
        "odds_id",
        "selection_team_id",
        "price",
        "fair_probability",
        "raw_status",
        "normalized_status",
        "metadata_version",
        "market_type",
        "match_stage",
        "provider_updated_at",
        "received_at",
        "age_seconds",
    }
)
_MARKET_QUALITY_FIELDS = frozenset(
    {"eligible", "blockers", "warnings", "metadata_version", "paired_at", "pair_skew_seconds"}
)
_MARKET_LEG_FIELDS = frozenset(
    {"odds_id", "selection_team_id", "price", "implied_probability", "fair_probability"}
)
_DRAFT_FIELDS = frozenset(
    {
        "complete",
        "blockers",
        "warnings",
        "observed_at",
        "statistics_cutoff",
        "roster_ready_count",
        "hero_ready_count",
    }
)
_DRAFT_SLOT_FIELDS = frozenset(
    {
        "side",
        "position",
        "account_id",
        "canonical_player_id",
        "player_name",
        "hero_id",
        "hero_name",
    }
)
_LIVE_FIELDS = frozenset(
    {
        "game_time_seconds",
        "radiant_kills",
        "dire_kills",
        "radiant_nw_lead",
        "first_blood",
        "received_at",
        "last_message_received_at",
        "last_state_change_received_at",
        "message_age_seconds",
        "effective_state_age_seconds",
        "connection_id",
        "reconnect_generation",
    }
)
_SYNC_FIELDS = frozenset(
    {
        "status",
        "p50_seconds",
        "p90_seconds",
        "jitter_seconds",
        "sample_size",
        "accepted_pair_ratio",
        "ambiguous_ratio",
        "outlier_ratio",
        "confidence",
        "calculated_at",
    }
)
_HISTORICAL_PREWARM_FIELDS = frozenset(
    {
        "team_strength_ready_count",
        "player_form_ready_count",
        "player_hero_ready_count",
        "latest_knowledge_cutoff",
    }
)
_RESULT_FIELDS = frozenset(
    {
        "winner_team_id",
        "basic_first_usable_at",
        "advanced_first_usable_at",
        "settled_at",
        "provider_conflict",
    }
)
_RESULT_EVIDENCE_FIELDS = frozenset(
    {
        "id",
        "provider",
        "provider_match_id",
        "winner_team_id",
        "result_observed_at",
        "first_usable_at",
        "raw_event_id",
        "normalizer_version",
        "identity_confidence",
        "conflict_status",
    }
)
_SNAPSHOT_FIELDS = frozenset({"id", "decision_at", "created_at", "mode"})
_SNAPSHOT_QUALITY_FIELDS = frozenset({"eligible", "blockers", "warnings"})
_LIVE_ANCHOR_FIELDS = frozenset({"raybet_live_anchor", "data_lag_seconds"})


class PublicMatchDataBoundaryMiddleware(BaseHTTPMiddleware):
    """Build fail-closed public projections for match and runtime endpoints.

    Canonical payloads intentionally contain more detail than the public product
    surface. New top-level or nested fields must be explicitly allowlisted here
    before they can cross the anonymous boundary.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        if (
            request.method != "GET"
            or response.status_code != 200
            or "application/json" not in response.headers.get("content-type", "")
        ):
            return response

        sanitize_match = _is_public_match_endpoint(request.url.path)
        sanitize_runtime = (
            request.url.path == "/api/runtime" and getattr(request.state, "auth_user", None) is None
        )
        if not sanitize_match and not sanitize_runtime:
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

        if sanitize_runtime:
            sanitized = _sanitize_runtime_payload(payload) if isinstance(payload, dict) else payload
        elif isinstance(payload, list):
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

    sanitized = _project_dict(payload, _PUBLIC_MATCH_SCALAR_FIELDS)
    _copy_projected_dict(sanitized, payload, "series_score", _SERIES_SCORE_FIELDS)
    _copy_projected_list(sanitized, payload, "series_maps", _SERIES_MAP_FIELDS)
    _copy_projected_dict(sanitized, payload, "team_a", _TEAM_FIELDS)
    _copy_projected_dict(sanitized, payload, "team_b", _TEAM_FIELDS)
    _copy_projected_list(sanitized, payload, "market", _MARKET_FIELDS)
    _copy_projected_dict(sanitized, payload, "market_quality", _MARKET_QUALITY_FIELDS)
    _copy_current_market_view(sanitized, payload)
    _copy_projected_dict(
        sanitized,
        payload,
        "snapshot_market_quality",
        _MARKET_QUALITY_FIELDS,
    )
    _copy_draft(sanitized, payload)
    _copy_projected_dict(sanitized, payload, "live", _LIVE_FIELDS)
    _copy_projected_dict(sanitized, payload, "sync", _SYNC_FIELDS)
    _copy_projected_dict(
        sanitized,
        payload,
        "historical_prewarm",
        _HISTORICAL_PREWARM_FIELDS,
    )
    _copy_projected_list(sanitized, payload, "market_timeline", _MARKET_FIELDS)
    _copy_projected_list(sanitized, payload, "live_timeline", _LIVE_FIELDS)
    _copy_projected_dict(sanitized, payload, "result", _RESULT_FIELDS)
    _copy_projected_list(sanitized, payload, "result_evidence", _RESULT_EVIDENCE_FIELDS)

    snapshot_summary = _sanitize_snapshot(payload.get("latest_snapshot"))
    sanitized["latest_snapshot"] = snapshot_summary
    sanitized["decisions"] = []
    sanitized["ai_access"] = {
        "required_entitlement": "ai_decisions",
        "analysis_available": snapshot_summary is not None,
        "updated_at": snapshot_summary.get("decision_at") if snapshot_summary else None,
        "completed_models": completed_models,
    }
    return sanitized


def _sanitize_snapshot(value: object) -> dict | None:
    if not isinstance(value, dict):
        return None
    result = _project_dict(value, _SNAPSHOT_FIELDS)
    market_quality = value.get("market_quality")
    if market_quality is None:
        if "market_quality" in value:
            result["market_quality"] = None
    elif isinstance(market_quality, dict):
        result["market_quality"] = _project_dict(market_quality, _MARKET_QUALITY_FIELDS)

    quality = value.get("quality")
    if quality is None:
        if "quality" in value:
            result["quality"] = None
    elif isinstance(quality, dict):
        public_quality = _project_dict(quality, _SNAPSHOT_QUALITY_FIELDS)
        anchors = quality.get("live_anchors")
        if isinstance(anchors, dict):
            public_quality["live_anchors"] = _project_dict(anchors, _LIVE_ANCHOR_FIELDS)
        result["quality"] = public_quality
    return result


def _copy_current_market_view(target: dict, source: dict) -> None:
    if "current_market_view" not in source:
        return
    value = source.get("current_market_view")
    if value is None:
        target["current_market_view"] = None
        return
    if not isinstance(value, dict):
        return
    public = {}
    if "overround" in value:
        public["overround"] = value["overround"]
    _copy_projected_dict(public, value, "team_a", _MARKET_LEG_FIELDS)
    _copy_projected_dict(public, value, "team_b", _MARKET_LEG_FIELDS)
    _copy_projected_dict(public, value, "quality", _MARKET_QUALITY_FIELDS)
    target["current_market_view"] = public


def _copy_draft(target: dict, source: dict) -> None:
    if "draft" not in source:
        return
    value = source.get("draft")
    if value is None:
        target["draft"] = None
        return
    if not isinstance(value, dict):
        return
    public = _project_dict(value, _DRAFT_FIELDS)
    slots = value.get("slots")
    if isinstance(slots, list):
        public["slots"] = [
            _project_dict(item, _DRAFT_SLOT_FIELDS) for item in slots if isinstance(item, dict)
        ]
    target["draft"] = public


def _copy_projected_dict(target: dict, source: dict, key: str, fields: frozenset[str]) -> None:
    if key not in source:
        return
    value = source.get(key)
    if value is None:
        target[key] = None
    elif isinstance(value, dict):
        target[key] = _project_dict(value, fields)


def _copy_projected_list(target: dict, source: dict, key: str, fields: frozenset[str]) -> None:
    if key not in source:
        return
    value = source.get(key)
    if value is None:
        target[key] = None
    elif isinstance(value, list):
        target[key] = [_project_dict(item, fields) for item in value if isinstance(item, dict)]


def _project_dict(value: dict, fields: frozenset[str]) -> dict:
    return {key: value[key] for key in fields if key in value}


def _sanitize_runtime_payload(payload: dict) -> dict:
    """Expose only coarse availability to anonymous dashboard viewers."""

    fields = (
        "overall",
        "observed_at",
        "live_state_max_age_seconds",
        "live_market_max_age_seconds",
    )
    result = {key: payload[key] for key in fields if key in payload}
    # Keep the existing frontend contract stable without exposing dependency
    # errors, worker metadata, provider names, counters, or internal diagnostics.
    result["workers"] = {}
    result["dependencies"] = {}
    return result
