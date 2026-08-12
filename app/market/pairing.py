from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from app.domain.market import MarketPairQuality
from app.time import elapsed_seconds


@dataclass(frozen=True)
class MarketPairLeg:
    provider_match_id: int
    odds_id: int
    canonical_series_id: UUID | None
    canonical_map_id: UUID | None
    market_type: str | None
    match_stage: str | None
    selection_team_id: UUID | None
    price: Decimal
    normalized_status: str | None
    metadata_version: str | None
    received_at: datetime


def evaluate_market_pair(
    legs: tuple[MarketPairLeg, ...],
    *,
    expected_series_id: UUID,
    expected_map_id: UUID | None,
    expected_team_ids: frozenset[UUID],
    decision_at: datetime,
    max_age_seconds: float,
    max_pair_skew_seconds: float,
) -> MarketPairQuality:
    blockers: list[str] = []
    warnings: list[str] = []
    if len(legs) != 2:
        blockers.append("MARKET_PAIR_CARDINALITY_INVALID")
        return _quality(blockers, warnings, decision_at, None, None)

    first, second = legs
    if first.provider_match_id != second.provider_match_id:
        blockers.append("MARKET_PAIR_MATCH_MISMATCH")
    if (
        first.canonical_series_id != expected_series_id
        or second.canonical_series_id != expected_series_id
    ):
        blockers.append("MARKET_PAIR_SERIES_MISMATCH")
    if expected_map_id is not None and (
        first.canonical_map_id != expected_map_id or second.canonical_map_id != expected_map_id
    ):
        blockers.append("MARKET_PAIR_MAP_MISMATCH")
    if first.market_type is None or first.market_type != second.market_type:
        blockers.append("MARKET_PAIR_TYPE_MISMATCH")
    if first.match_stage is None or first.match_stage != second.match_stage:
        blockers.append("MARKET_PAIR_STAGE_MISMATCH")
    if first.odds_id == second.odds_id:
        blockers.append("MARKET_PAIR_DUPLICATE_ODDS")
    selection_ids = {first.selection_team_id, second.selection_team_id}
    if None in selection_ids or len(selection_ids) != 2:
        blockers.append("MARKET_PAIR_SELECTION_INVALID")
    elif selection_ids != expected_team_ids:
        blockers.append("MARKET_PAIR_TEAMS_MISMATCH")
    if first.price <= 1 or second.price <= 1:
        blockers.append("MARKET_PAIR_PRICE_INVALID")

    ages = [elapsed_seconds(decision_at, leg.received_at) for leg in legs]
    if any(age < 0 for age in ages):
        blockers.append("MARKET_PAIR_FUTURE_OBSERVATION")
    if any(age > max_age_seconds for age in ages):
        blockers.append("MARKET_PAIR_STALE_LEG")
    pair_skew = abs(elapsed_seconds(first.received_at, second.received_at))
    if pair_skew > max_pair_skew_seconds:
        blockers.append("MARKET_PAIR_SKEW_EXCEEDED")

    versions = {leg.metadata_version for leg in legs}
    metadata_version = first.metadata_version if len(versions) == 1 else None
    if None in versions or len(versions) != 1:
        blockers.append("MARKET_PAIR_METADATA_MISMATCH")

    statuses = {leg.normalized_status or "UNKNOWN" for leg in legs}
    if statuses & {"SUSPENDED", "CLOSED"}:
        blockers.append("MARKET_NOT_OPEN")
    elif statuses != {"OPEN_CONFIRMED"}:
        warnings.append("MARKET_STATUS_UNKNOWN")

    return _quality(blockers, warnings, decision_at, pair_skew, metadata_version)


def _quality(
    blockers: list[str],
    warnings: list[str],
    paired_at: datetime,
    pair_skew: float | None,
    metadata_version: str | None,
) -> MarketPairQuality:
    return MarketPairQuality(
        eligible=not blockers,
        blockers=tuple(dict.fromkeys(blockers)),
        warnings=tuple(dict.fromkeys(warnings)),
        metadata_version=metadata_version,
        paired_at=paired_at,
        pair_skew_seconds=pair_skew,
    )
