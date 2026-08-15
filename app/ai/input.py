"""Compose the exact deterministic object sent to AI providers."""

from typing import Any

from app.ai.context_summary import build_ai_context_summary
from app.ai.view import build_ai_view
from app.domain.snapshot import DecisionSnapshot

AI_VIEW_VERSION = "ai-view-v6"


def build_ai_input(
    snapshot: DecisionSnapshot,
    *,
    max_live_data_lag_seconds: float = 120.0,
) -> dict[str, Any]:
    """Build the provider input without adding non-deterministic interpretation.

    The base ai-view remains the source evidence. ``ai_context_summary`` is a
    semantic compression derived entirely from that evidence and must never be
    treated as an independent signal. The composed provider-facing view has its
    own version because adding or changing this summary changes model input.

    ``AiCoordinator`` appends the provider-scoped virtual bankroll and prior
    decisions to this deterministic base before sending the exact bytes.
    """
    view = build_ai_view(
        snapshot,
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
