from datetime import UTC, datetime

from app.draft.features import build_draft_curve


def test_curve_uses_real_support_without_treating_coverage_as_confidence() -> None:
    result = {
        "model_version": "test",
        "pure_minute_table": [],
        "minute_table": [
            {
                "minute": 20,
                "win_rate_graph": 3.5,
                "match_percentage": 92.0,
                "support": 127,
            }
        ],
    }

    curve = build_draft_curve(
        result,
        current_minute=20,
        statistics_cutoff=datetime(2026, 1, 1, tzinfo=UTC),
        data_version="fixture",
    )

    assert curve.points[0].support == 127
    assert curve.points[0].confidence is None


def test_curve_does_not_fabricate_support_from_match_percentage() -> None:
    result = {
        "model_version": "test",
        "pure_minute_table": [],
        "minute_table": [{"minute": 20, "win_rate_graph": -1.0, "match_percentage": 75.0}],
    }

    curve = build_draft_curve(
        result,
        current_minute=None,
        statistics_cutoff=datetime(2026, 1, 1, tzinfo=UTC),
        data_version="fixture",
    )

    assert curve.points[0].support is None
    assert curve.points[0].confidence is None
