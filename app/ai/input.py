"""Compose the exact deterministic object sent to AI providers."""

from typing import Any

from app.ai.context_profiles import build_context_profile_view
from app.ai.context_summary import build_ai_context_summary
from app.ai.versions import AI_VIEW_VERSION as AI_VIEW_VERSION
from app.domain.snapshot import DecisionSnapshot


def build_ai_input(
    snapshot: DecisionSnapshot,
    *,
    max_live_data_lag_seconds: float = 120.0,
    ai_view_version: str = AI_VIEW_VERSION,
) -> dict[str, Any]:
    """Build the provider input without adding non-deterministic interpretation.

    Production calls keep using the frozen/current ``AI_VIEW_VERSION`` path.
    Explicit experiment callers may request one registered context profile; the
    profile is derived from the same immutable snapshot and rejects unknown
    versions fail-closed.

    ``ai_context_summary`` is semantic compression derived entirely from the
    selected view and must never be treated as an independent signal.
    ``AiCoordinator`` appends provider-scoped virtual bankroll and prior
    decisions after this deterministic base is built.
    """
    view = build_context_profile_view(
        snapshot,
        ai_view_version=ai_view_version,
        max_live_data_lag_seconds=max_live_data_lag_seconds,
    )
    summary = build_ai_context_summary(view)
    # Version labels remain audit identity on AiDecisionRecord but are not match evidence.
    provider_view = {key: value for key, value in view.items() if key != "ai_view_version"}
    provider_summary = {
        key: value for key, value in summary.items() if key != "context_summary_version"
    }
    return {
        **provider_view,
        "ai_context_summary": provider_summary,
    }
