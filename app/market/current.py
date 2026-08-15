"""Request-time evaluation of the current RayBet winner market.

This is the single implementation shared by the web dashboard and the WeChat
ClawBot channel.  Both surfaces derive the same freshest complete Team A /
Team B pair and evaluate it with the same identity, freshness, skew, status,
and metadata rules, so a WeChat odds query never disagrees with the dashboard.
"""

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from app.domain.market import MarketPairQuality
from app.market.pairing import MarketPairLeg, evaluate_market_pair
from app.models import CanonicalSeries, OddsObservationRecord


def map_market_stages(map_number: int | None, *, best_of: int | None = None) -> tuple[str, ...]:
    if map_number is None:
        return ()
    stages = (
        f"r{map_number}",
        f"Map r{map_number}",
        f"map r{map_number}",
        f"Map {map_number}",
        f"map {map_number}",
    )
    if best_of is not None and map_number == best_of:
        # The deciding map's per-map winner market is withdrawn by RayBet
        # (r{n} goes stale, status 4) while the series winner ("final")
        # market stays live; for the deciding map that market IS the map
        # winner, so it joins the candidate stages and the freshest eligible
        # pair wins.
        stages += ("final",)
    return stages


def market_pair_leg(record: OddsObservationRecord) -> MarketPairLeg:
    return MarketPairLeg(
        provider_match_id=record.provider_match_id,
        odds_id=record.odds_id,
        canonical_series_id=record.canonical_series_id,
        canonical_map_id=record.canonical_map_id,
        market_type=record.market_type,
        match_stage=record.match_stage,
        selection_team_id=record.selection_team_id,
        price=record.price,
        normalized_status=record.normalized_status,
        metadata_version=record.metadata_version,
        received_at=record.received_at,
    )


def evaluate_current_market_pair(
    rows: Sequence[OddsObservationRecord],
    *,
    series: CanonicalSeries | None,
    canonical_map_id: UUID | None,
    observed_at: datetime,
    live_market_max_age_seconds: float,
    market_max_pair_skew_seconds: float,
) -> tuple[tuple[OddsObservationRecord, OddsObservationRecord], MarketPairQuality] | None:
    """Pick and evaluate the freshest complete A/B market pair.

    Mirrors the snapshot builder's pairing rules: candidate legs are grouped
    by (provider match, market type, match stage), only the latest observation
    per odds id competes, and the freshest eligible pair wins.  A stale or
    suspended candidate is returned only when no eligible pair exists, so
    callers can display it as degraded rather than pretend it is healthy.
    """
    if series is None or series.team_a_id is None or series.team_b_id is None:
        return None
    team_ids = frozenset({series.team_a_id, series.team_b_id})
    latest_by_odds: dict[int, OddsObservationRecord] = {}
    for row in rows:
        current = latest_by_odds.get(row.odds_id)
        if current is None or row.received_at > current.received_at:
            latest_by_odds[row.odds_id] = row
    grouped: dict[tuple[int, str | None, str | None], dict[UUID, OddsObservationRecord]] = {}
    for row in latest_by_odds.values():
        if row.selection_team_id not in team_ids:
            continue
        grouped.setdefault((row.provider_match_id, row.market_type, row.match_stage), {})[
            row.selection_team_id
        ] = row
    evaluated: list[
        tuple[float, tuple[OddsObservationRecord, OddsObservationRecord], MarketPairQuality]
    ] = []
    for (_provider_match_id, _market_type, match_stage), by_team in grouped.items():
        if set(by_team) != team_ids:
            continue
        legs = (
            by_team[series.team_a_id],
            by_team[series.team_b_id],
        )
        quality = evaluate_market_pair(
            tuple(market_pair_leg(record) for record in legs),
            expected_series_id=series.id,
            # The deciding-map fallback uses the series-scoped "final" market
            # whose observations carry no map identity; map checks are skipped
            # for that stage by design.
            expected_map_id=None if match_stage == "final" else canonical_map_id,
            expected_team_ids=team_ids,
            decision_at=observed_at,
            max_age_seconds=live_market_max_age_seconds,
            max_pair_skew_seconds=market_max_pair_skew_seconds,
        )
        freshness = max(legs[0].received_at, legs[1].received_at)
        evaluated.append((freshness, legs, quality))
    if not evaluated:
        return None
    # Prefer an eligible pair (open, fresh) over a stale/suspended candidate;
    # this is what lets the live "final" market of a deciding map replace the
    # delisted per-map r{n} market.
    eligible = [candidate for candidate in evaluated if candidate[2].eligible]
    _, legs, quality = max(eligible or evaluated, key=lambda item: item[0])
    return legs, quality
