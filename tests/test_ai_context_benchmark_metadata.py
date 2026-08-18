import pytest

from app.ai.context_profiles import (
    NO_PLAYER_FORM_CONTEXT_VERSION,
    SCHEMA_ALIGNED_CONTEXT_VERSION,
)
from app.web.quality import annotate_context_experiments


def test_context_benchmark_uses_aligned_full_as_ablation_reference() -> None:
    production = _row("ai-view-v6", accuracy=0.60, brier=0.21)
    aligned = _row(SCHEMA_ALIGNED_CONTEXT_VERSION, accuracy=0.66, brier=0.18)
    no_form = _row(NO_PLAYER_FORM_CONTEXT_VERSION, accuracy=0.61, brier=0.23)
    report = {"experiments": [production, aligned, no_form]}

    annotate_context_experiments(report)

    assert production["context_experiment"] is None
    assert aligned["context_experiment"]["reference_ai_view_version"] == "ai-view-v6"
    assert aligned["context_reference"]["ai_view_version"] == "ai-view-v6"
    assert aligned["delta_vs_context_reference"]["forecast_accuracy"] == pytest.approx(0.06)
    assert aligned["delta_vs_context_reference"]["brier_improvement"] == pytest.approx(0.03)

    assert (
        no_form["context_experiment"]["reference_ai_view_version"] == SCHEMA_ALIGNED_CONTEXT_VERSION
    )
    assert no_form["context_experiment"]["removed_evidence"] == ["player_form"]
    assert no_form["context_reference"]["ai_view_version"] == SCHEMA_ALIGNED_CONTEXT_VERSION
    assert no_form["delta_vs_context_reference"]["forecast_accuracy"] == pytest.approx(-0.05)
    assert no_form["delta_vs_context_reference"]["brier_improvement"] == pytest.approx(-0.05)


def _row(ai_view_version: str, *, accuracy: float, brier: float) -> dict:
    return {
        "experiment": {
            "provider": "openai",
            "model": "gpt-5.6-terra",
            "prompt_version": "decision-analyst-v5.1-output",
            "decision_policy_version": "shadow-tournament-portfolio-v3",
            "ai_view_version": ai_view_version,
        },
        "samples": {"forecast_maps": 20},
        "quality": {
            "forecast_accuracy": accuracy,
            "average_brier_score": brier,
            "average_log_loss": 0.6,
            "calibration_error": 0.1,
            "average_clv": 0.01,
            "market_brier_improvement": 0.02,
            "abstention_rate": 0.4,
        },
        "latency": {"average_seconds": 3.0, "p95_seconds": 5.0},
        "portfolio": {"realized_roi": 0.02, "worst_event_drawdown_pct": 0.1},
    }
