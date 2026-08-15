from datetime import UTC, datetime

from app.providers.dltv.results import normalize_match_result


def _payload(*, started_at: str | None) -> dict:
    return {
        "match_id": 12345,
        "winner": "radiant",
        "game_time": 2100,
        "db": {
            "first_team": {"id": 1, "is_radiant": True},
            "second_team": {"id": 2, "is_radiant": False},
            "series": {"event_id": 9, "started_at": started_at},
        },
    }


def test_dltv_missing_started_at_is_explicitly_estimated() -> None:
    fetched_at = datetime(2026, 8, 16, 2, 0, tzinfo=UTC)
    bundle = normalize_match_result(_payload(started_at=None), fetched_at=fetched_at)
    assert bundle.match.started_at == fetched_at
    assert bundle.match.started_at_estimated is True
    assert bundle.warnings == ("STARTED_AT_ESTIMATED_FROM_FETCHED_AT",)


def test_dltv_published_started_at_is_not_estimated() -> None:
    fetched_at = datetime(2026, 8, 16, 2, 0, tzinfo=UTC)
    bundle = normalize_match_result(
        _payload(started_at="2026-08-16T01:00:00+00:00"),
        fetched_at=fetched_at,
    )
    assert bundle.match.started_at == datetime(2026, 8, 16, 1, 0, tzinfo=UTC)
    assert bundle.match.started_at_estimated is False
    assert bundle.warnings == ()
