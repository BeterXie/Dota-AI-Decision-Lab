"""Compose the exact deterministic object sent to AI providers."""

from typing import Any

from app.ai.context_summary import build_ai_context_summary
from app.ai.view import build_ai_view
from app.domain.snapshot import DecisionSnapshot


def build_ai_input(
    snapshot: DecisionSnapshot,
    *,
    max_live_data_lag_seconds: float = 120.0,
) -> dict[str, Any]:
    """Build the provider input without adding non-deterministic interpretation.

    The base ai-view remains the source evidence. ``ai_context_summary`` is a
    semantic compression derived entirely from that evidence and must never be
    treated as an independent signal.
    """
    view = build_ai_view(
        snapshot,
        max_live_data_lag_seconds=max_live_data_lag_seconds,
    )
    return {
        **view,
        "ai_context_summary": build_ai_context_summary(view),
    }
