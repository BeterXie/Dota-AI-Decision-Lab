from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from math import ceil
from statistics import median, pstdev
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.domain.live import CalibrationPair, LiveSynchronizationEstimate
from app.models import (
    DltvLiveObservationRecord,
    LiveCalibrationPairRecord,
    LiveSyncEstimateRecord,
    OddsObservationRecord,
)
from app.time import ensure_utc


@dataclass(frozen=True)
class CalibrationSignal:
    received_at: datetime
    event_type: str
    signal_id: str | None = None


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
    ambiguity_margin_seconds: float = 0.5,
    min_accepted_pair_ratio: float = 0.6,
) -> LiveSynchronizationEstimate:
    if pairing_window_seconds <= 0 or min_samples <= 0:
        raise ValueError("pairing window and minimum samples must be positive")
    if safe_seconds < 0 or caution_seconds < safe_seconds:
        raise ValueError("live synchronization thresholds are invalid")
    if ambiguity_margin_seconds < 0 or not 0 < min_accepted_pair_ratio <= 1:
        raise ValueError("live synchronization quality thresholds are invalid")

    estimate, _pairs = _calibrate(
        canonical_map_id,
        raybet_signals,
        dltv_signals,
        calculated_at=calculated_at,
        pairing_window_seconds=pairing_window_seconds,
        safe_seconds=safe_seconds,
        caution_seconds=caution_seconds,
        min_samples=min_samples,
        ambiguity_margin_seconds=ambiguity_margin_seconds,
        min_accepted_pair_ratio=min_accepted_pair_ratio,
    )
    return estimate


def _calibrate(
    canonical_map_id: UUID,
    raybet_signals: Sequence[CalibrationSignal],
    dltv_signals: Sequence[CalibrationSignal],
    *,
    calculated_at: datetime,
    pairing_window_seconds: float,
    safe_seconds: float,
    caution_seconds: float,
    min_samples: int,
    ambiguity_margin_seconds: float,
    min_accepted_pair_ratio: float,
) -> tuple[LiveSynchronizationEstimate, tuple[CalibrationPair, ...]]:
    available_dltv = list(enumerate(sorted(dltv_signals, key=lambda item: item.received_at)))
    pairs: list[CalibrationPair] = []
    lags: list[float] = []
    for raybet_index, raybet in enumerate(
        sorted(raybet_signals, key=lambda item: item.received_at)
    ):
        forward = [
            (index, signal, (signal.received_at - raybet.received_at).total_seconds())
            for index, signal in available_dltv
            if signal.received_at >= raybet.received_at
        ]
        candidates = sorted(forward, key=lambda candidate: candidate[2])
        raybet_id = _signal_id(raybet, raybet_index)
        if not candidates or candidates[0][2] > pairing_window_seconds:
            pairs.append(_rejected_pair(raybet, raybet_id, "NO_FORWARD_CANDIDATE"))
            continue
        nearest_index, nearest, lag = candidates[0]
        uniqueness_margin = (
            candidates[1][2] - lag if len(candidates) > 1 else pairing_window_seconds - lag
        )
        if len(candidates) > 1 and uniqueness_margin <= ambiguity_margin_seconds:
            pairs.append(
                CalibrationPair(
                    raybet_signal_id=raybet_id,
                    dltv_signal_id=_signal_id(nearest, nearest_index),
                    raybet_received_at=raybet.received_at,
                    dltv_received_at=nearest.received_at,
                    lag_seconds=lag,
                    raybet_signal_type=raybet.event_type,
                    dltv_signal_type=nearest.event_type,
                    uniqueness_margin_seconds=uniqueness_margin,
                    accepted=False,
                    reject_reason="AMBIGUOUS_NEAREST",
                )
            )
            continue
        lags.append(lag)
        pairs.append(
            CalibrationPair(
                raybet_signal_id=raybet_id,
                dltv_signal_id=_signal_id(nearest, nearest_index),
                raybet_received_at=raybet.received_at,
                dltv_received_at=nearest.received_at,
                lag_seconds=lag,
                raybet_signal_type=raybet.event_type,
                dltv_signal_type=nearest.event_type,
                uniqueness_margin_seconds=uniqueness_margin,
                accepted=True,
            )
        )
        available_dltv = [item for item in available_dltv if item[0] != nearest_index]

    sample_size = len(lags)
    if not lags:
        estimated_lag = p50 = p90 = jitter = None
    else:
        absolute_lags = [abs(value) for value in lags]
        estimated_lag = median(lags)
        p50 = median(absolute_lags)
        p90 = _nearest_rank(absolute_lags, 0.90)
        jitter = pstdev(lags) if sample_size > 1 else 0.0

    # RayBet signals arrive far more often than DLTV state changes, so most
    # RayBet signals have no forward DLTV candidate inside the pairing window.
    # That is a cadence mismatch, not a pairing-quality failure: ratio metrics
    # are computed over pairs that HAD a candidate.
    candidate_pairs = [pair for pair in pairs if pair.reject_reason != "NO_FORWARD_CANDIDATE"]
    total_pairs = len(candidate_pairs)
    accepted_ratio = sample_size / total_pairs if total_pairs else 0.0
    ambiguous_count = sum(pair.reject_reason == "AMBIGUOUS_NEAREST" for pair in candidate_pairs)
    ambiguous_ratio = ambiguous_count / total_pairs if total_pairs else 0.0
    outlier_count = sum(
        pair.reject_reason not in {None, "AMBIGUOUS_NEAREST"} for pair in candidate_pairs
    )
    outlier_ratio = outlier_count / total_pairs if total_pairs else 0.0

    if total_pairs == 0:
        confidence = "LOW"
        status = "UNKNOWN"
    elif sample_size < min_samples or accepted_ratio < min_accepted_pair_ratio:
        confidence = "LOW"
        status = "CALIBRATING"
    else:
        confidence = "HIGH" if sample_size >= 8 else "MEDIUM"
        if (
            p90 is not None
            and jitter is not None
            and p90 <= safe_seconds
            and jitter <= safe_seconds
            and ambiguous_ratio == 0
        ):
            status = "SAFE"
        elif (
            p90 is not None
            and jitter is not None
            and p90 <= caution_seconds
            and jitter <= caution_seconds
        ):
            status = "CAUTION"
        else:
            status = "UNSAFE"

    estimate = LiveSynchronizationEstimate(
        canonical_map_id=str(canonical_map_id),
        estimated_lag_seconds=estimated_lag,
        p50_seconds=p50,
        p90_seconds=p90,
        jitter_seconds=jitter,
        sample_size=sample_size,
        accepted_pair_ratio=accepted_ratio,
        ambiguous_ratio=ambiguous_ratio,
        outlier_ratio=outlier_ratio,
        confidence=confidence,
        status=status,
        calculated_at=calculated_at,
    )
    return estimate, tuple(pairs)


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
        existing = await session.scalar(
            select(LiveSyncEstimateRecord).where(
                LiveSyncEstimateRecord.canonical_map_id == canonical_map_id,
                LiveSyncEstimateRecord.calculated_at == as_of,
            )
        )
        if existing is not None:
            return _estimate_from_record(existing)
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
        estimate, pairs = _calibrate(
            canonical_map_id,
            _raybet_signals(odds, self._settings.significant_odds_move),
            _dltv_signals(live, self._settings.live_sync_nw_signal_threshold),
            calculated_at=as_of,
            pairing_window_seconds=self._settings.live_sync_calibration_window_seconds,
            safe_seconds=self._settings.live_sync_safe_seconds,
            caution_seconds=self._settings.live_sync_caution_seconds,
            min_samples=self._settings.live_sync_min_samples,
            ambiguity_margin_seconds=self._settings.live_sync_ambiguity_margin_seconds,
            min_accepted_pair_ratio=self._settings.live_sync_min_accepted_pair_ratio,
        )
        session.add(
            LiveSyncEstimateRecord(
                canonical_map_id=canonical_map_id,
                estimated_lag_seconds=estimate.estimated_lag_seconds,
                p50_seconds=estimate.p50_seconds,
                p90_seconds=estimate.p90_seconds,
                jitter_seconds=estimate.jitter_seconds,
                sample_size=estimate.sample_size,
                accepted_pair_ratio=estimate.accepted_pair_ratio,
                ambiguous_ratio=estimate.ambiguous_ratio,
                outlier_ratio=estimate.outlier_ratio,
                confidence=estimate.confidence,
                status=estimate.status,
                calculated_at=estimate.calculated_at,
            )
        )
        for pair in pairs:
            if pair.reject_reason == "NO_FORWARD_CANDIDATE":
                # Cadence-mismatch noise: no DLTV signal id, no lag, nothing to
                # audit.  Persisting thousands of these per live match is bloat.
                continue
            session.add(
                LiveCalibrationPairRecord(
                    canonical_map_id=canonical_map_id,
                    calculated_at=as_of,
                    **pair.model_dump(),
                )
            )
        return estimate


def _estimate_from_record(record: LiveSyncEstimateRecord) -> LiveSynchronizationEstimate:
    return LiveSynchronizationEstimate(
        canonical_map_id=str(record.canonical_map_id),
        estimated_lag_seconds=record.estimated_lag_seconds,
        p50_seconds=record.p50_seconds,
        p90_seconds=record.p90_seconds,
        jitter_seconds=record.jitter_seconds,
        sample_size=record.sample_size,
        accepted_pair_ratio=record.accepted_pair_ratio,
        ambiguous_ratio=record.ambiguous_ratio,
        outlier_ratio=record.outlier_ratio,
        confidence=record.confidence,
        status=record.status,
        calculated_at=ensure_utc(record.calculated_at),
    )


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
            signals.append(
                CalibrationSignal(
                    observation.received_at,
                    "MARKET_REPRICE",
                    str(observation.id),
                )
            )
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
                signals.append(
                    CalibrationSignal(
                        observation.received_at,
                        "LIVE_STATE_CHANGE",
                        str(observation.id),
                    )
                )
        previous = observation
    return signals


def _nearest_rank(values: Sequence[float], percentile: float) -> float:
    ordered = sorted(values)
    return ordered[max(ceil(percentile * len(ordered)) - 1, 0)]


def _signal_id(signal: CalibrationSignal, index: int) -> str:
    return signal.signal_id or f"{signal.event_type}:{signal.received_at.isoformat()}:{index}"


def _rejected_pair(
    raybet: CalibrationSignal,
    raybet_id: str,
    reason: str,
) -> CalibrationPair:
    return CalibrationPair(
        raybet_signal_id=raybet_id,
        dltv_signal_id=None,
        raybet_received_at=raybet.received_at,
        dltv_received_at=None,
        lag_seconds=None,
        raybet_signal_type=raybet.event_type,
        dltv_signal_type=None,
        uniqueness_margin_seconds=None,
        accepted=False,
        reject_reason=reason,
    )
