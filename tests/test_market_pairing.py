from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from app.market.fair_probability import remove_vig
from app.market.pairing import MarketPairLeg, evaluate_market_pair


def _leg(
    *,
    odds_id: int,
    team_id: UUID,
    received_at: datetime,
    price: str = "2.00",
    stage: str = "Map 1",
    status: str = "UNKNOWN",
    series_id: UUID,
    map_id: UUID,
) -> MarketPairLeg:
    return MarketPairLeg(
        provider_match_id=10,
        odds_id=odds_id,
        canonical_series_id=series_id,
        canonical_map_id=map_id,
        market_type="match_winner",
        match_stage=stage,
        selection_team_id=team_id,
        price=Decimal(price),
        normalized_status=status,
        metadata_version="registry-v1",
        received_at=received_at,
    )


def _quality(*legs: MarketPairLeg, expected_team_ids: frozenset[UUID] | None = None):
    series_id = legs[0].canonical_series_id
    map_id = legs[0].canonical_map_id
    assert series_id is not None and map_id is not None
    return evaluate_market_pair(
        legs,
        expected_series_id=series_id,
        expected_map_id=map_id,
        expected_team_ids=expected_team_ids
        or frozenset(leg.selection_team_id for leg in legs if leg.selection_team_id),
        decision_at=datetime(2026, 8, 12, 12, 0, 10, tzinfo=UTC),
        max_age_seconds=30,
        max_pair_skew_seconds=5,
    )


def test_market_pair_accepts_exact_teams_and_exposes_unknown_status() -> None:
    series_id, map_id, team_a, team_b = uuid4(), uuid4(), uuid4(), uuid4()
    now = datetime(2026, 8, 12, 12, 0, 8, tzinfo=UTC)
    quality = _quality(
        _leg(odds_id=1, team_id=team_a, received_at=now, series_id=series_id, map_id=map_id),
        _leg(odds_id=2, team_id=team_b, received_at=now, series_id=series_id, map_id=map_id),
    )

    assert quality.eligible is True
    assert quality.warnings == ("MARKET_STATUS_UNKNOWN",)
    assert remove_vig(2.0, 2.0) == (0.5, 0.5, 1.0)


def test_market_pair_rejects_duplicate_team_mixed_stage_stale_and_skewed_legs() -> None:
    series_id, map_id, team_a = uuid4(), uuid4(), uuid4()
    now = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)
    first = _leg(
        odds_id=1,
        team_id=team_a,
        received_at=now - timedelta(seconds=40),
        series_id=series_id,
        map_id=map_id,
    )
    second = _leg(
        odds_id=2,
        team_id=team_a,
        received_at=now,
        stage="Map 2",
        series_id=series_id,
        map_id=map_id,
    )
    quality = _quality(first, second, expected_team_ids=frozenset((team_a, uuid4())))

    assert quality.eligible is False
    assert "MARKET_PAIR_SELECTION_INVALID" in quality.blockers
    assert "MARKET_PAIR_STAGE_MISMATCH" in quality.blockers
    assert "MARKET_PAIR_STALE_LEG" in quality.blockers
    assert "MARKET_PAIR_SKEW_EXCEEDED" in quality.blockers
