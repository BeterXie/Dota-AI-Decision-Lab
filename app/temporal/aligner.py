from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from math import ceil
from statistics import median, pstdev
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.domain.live import LiveSynchronizationEstimate
from app.models import DltvLiveObservationRecord, LiveSyncEstimateRecord, OddsObservationRecord


@dataclass(frozen=True)
class CalibrationSignal:
    received_at: datetime
    event_type: str


def estimate_synchronization(
    canonical_map_id: UUID,
    raybet_signals: Sequence[CalibrationSignal],
    dltv_signals: Sequence[CalibrationSignal],
    *,
    calculated_at: datetime,
    pairing_window_seconds: float,
    safe_seconds: float,
    caution_seconds: float,
    min_samples: int,
) -> LiveSynchronizationEstimate:
    if pairing_window_seconds <= 0 or min_samples <= 0:
        raise ValueError("pairing window and minimum samples must be positive")
    if safe_seconds < 0 or caution_seconds < safe_seconds:
        raise ValueError("live synchronization thresholds are invalid")

    unmatched_dltv = sorted(dltv_signals, key=lambda signal: signal.received_at)
    lags: list[float] = []
    for raybet in sorted(raybet_signals, key=lambda signal: signal.received_at):
        if not unmatched_dltv:
            break
        nearest_index = min(
            range(len(unmatched_dltv)),
            key=lambda index: abs(
                (unmatched_dltv[index].received_at - raybet.received_at).total_seconds()
            ),
        )
        lag = (unmatched_dltv[nearest_index].received_at - raybet.received_at).total_seconds()
        if abs(lag) <= pairing_window_seconds:
            lags.append(lag)
            unmatched_dltv.pop(nearest_index)

    sample_size = len(lags)
    if not lags:
        estimated_lag = p50 = p90 = jitter = None
    else:
        absolute_lags = [abs(value) for value in lags]
        estimated_lag = median(lags)
        p50 = median(absolute_lags)
        p90 = _nearest_rank(absolute_lags, 0.90)
        jitter = pstdev(lags) if sample_size > 1 else 0.0

    if sample_size < min_samples:
        confidence = "LOW"
        status = "UNKNOWN"
    else:
        confidence = "HIGH" if sample_size >= 8 else "MEDIUM"
        if p90 is not None and p90 <= safe_seconds:
            status = "SAFE"
        elif p90 is not None and p90 <= caution_seconds:
            status = "CAUTION"
        else:
            status = "UNSAFE"

    return LiveSynchronizationEstimate(
        canonical_map_id=str(canonical_map_id),
        estimated_lag_seconds=estimated_lag,
        p50_seconds=p50,
        p90_seconds=p90,
        jitter_seconds=jitter,
        sample_size=sample_size,
        confidence=confidence,
        status=status,
        calculated_at=calculated_at,
    )


class TemporalAligner:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def calculate(
        self,
        session: AsyncSession,
        *,
        canonical_map_id: UUID,
        as_of: datetime,
    ) -> LiveSynchronizationEstimate:
        odds = list(
            reversed(
                (
                    await session.scalars(
                        select(OddsObservationRecord)
                        .where(
                            OddsObservationRecord.canonical_map_id == canonical_map_id,
                            OddsObservationRecord.received_at <= as_of,
                        )
                        .order_by(OddsObservationRecord.received_at.desc())
                        .limit(500)
                    )
                ).all()
            )
        )
        live = list(
            reversed(
                (
                    await session.scalars(
                        select(DltvLiveObservationRecord)
                        .where(
                            DltvLiveObservationRecord.canonical_map_id == canonical_map_id,
                            DltvLiveObservationRecord.received_at <= as_of,
                        )
                        .order_by(DltvLiveObservationRecord.received_at.desc())
                        .limit(500)
                    )
                ).all()
            )
        )
        estimate = estimate_synchronization(
            canonical_map_id,
            _raybet_signals(odds, self._settings.significant_odds_move),
            _dltv_signals(live, self._settings.live_sync_nw_signal_threshold),
            calculated_at=as_of,
            pairing_window_seconds=self._settings.live_sync_calibration_window_seconds,
            safe_seconds=self._settings.live_sync_safe_seconds,
            caution_seconds=self._settings.live_sync_caution_seconds,
            min_samples=self._settings.live_sync_min_samples,
        )
        session.add(
            LiveSyncEstimateRecord(
                canonical_map_id=canonical_map_id,
                estimated_lag_seconds=estimate.estimated_lag_seconds,
                p50_seconds=estimate.p50_seconds,
                p90_seconds=estimate.p90_seconds,
                jitter_seconds=estimate.jitter_seconds,
                sample_size=estimate.sample_size,
                confidence=estimate.confidence,
                status=estimate.status,
                calculated_at=estimate.calculated_at,
            )
        )
        return estimate


def _raybet_signals(
    observations: Sequence[OddsObservationRecord], significant_move: float
) -> list[CalibrationSignal]:
    previous_by_odds_id: dict[int, OddsObservationRecord] = {}
    signals: list[CalibrationSignal] = []
    for observation in observations:
        previous = previous_by_odds_id.get(observation.odds_id)
        previous_by_odds_id[observation.odds_id] = observation
        if previous is None:
            continue
        price_move = abs(float(observation.price) / float(previous.price) - 1.0)
        status_changed = observation.raw_status != previous.raw_status
        if price_move >= significant_move or status_changed:
            signals.append(CalibrationSignal(observation.received_at, "MARKET_REPRICE"))
    return signals


def _dltv_signals(
    observations: Sequence[DltvLiveObservationRecord], nw_threshold: int
) -> list[CalibrationSignal]:
    signals: list[CalibrationSignal] = []
    previous: DltvLiveObservationRecord | None = None
    for observation in observations:
        if previous is not None:
            kills_changed = (
                observation.radiant_kills is not None
                and observation.dire_kills is not None
                and previous.radiant_kills is not None
                and previous.dire_kills is not None
                and (
                    observation.radiant_kills != previous.radiant_kills
                    or observation.dire_kills != previous.dire_kills
                )
            )
            nw_changed = (
                observation.radiant_nw_lead is not None
                and previous.radiant_nw_lead is not None
                and abs(observation.radiant_nw_lead - previous.radiant_nw_lead) >= nw_threshold
            )
            if kills_changed or nw_changed:
                signals.append(CalibrationSignal(observation.received_at, "LIVE_STATE_CHANGE"))
        previous = observation
    return signals


def _nearest_rank(values: Sequence[float], percentile: float) -> float:
    ordered = sorted(values)
    return ordered[max(ceil(percentile * len(ordered)) - 1, 0)]
