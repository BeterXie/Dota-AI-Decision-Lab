from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.jobs import JobType
from app.jobs.repository import JobRepository
from app.market.pairing import MarketPairLeg, evaluate_market_pair
from app.models import DecisionFutureOdds, DecisionSnapshotRecord, OddsObservationRecord

CLOSING_POLICY_VERSION = "closing-policy-v1"


class FutureOddsCaptureType(StrEnum):
    TIME_HORIZON = "TIME_HORIZON"
    CLOSING = "CLOSING"


class FutureOddsService:
    def __init__(
        self,
        jobs: JobRepository,
        *,
        market_max_age_seconds: float = 30.0,
        market_max_pair_skew_seconds: float = 5.0,
    ) -> None:
        self._jobs = jobs
        self._market_max_age_seconds = market_max_age_seconds
        self._market_max_pair_skew_seconds = market_max_pair_skew_seconds

    async def schedule(
        self,
        session: AsyncSession,
        *,
        snapshot_id: UUID,
        decision_at: datetime,
        horizons_seconds: tuple[int, ...],
    ) -> int:
        scheduled = 0
        for horizon in horizons_seconds:
            if horizon <= 0:
                raise ValueError("future odds horizons must be positive")
            due_at = decision_at + timedelta(seconds=horizon)
            await self._jobs.enqueue(
                session,
                job_type=JobType.CAPTURE_FUTURE_ODDS,
                dedupe_key=f"future-odds:{snapshot_id}:{horizon}",
                payload={
                    "snapshot_id": str(snapshot_id),
                    "capture_type": FutureOddsCaptureType.TIME_HORIZON.value,
                    "horizon_seconds": horizon,
                    "due_at": due_at.isoformat(),
                },
                not_before=due_at,
            )
            scheduled += 1
        return scheduled

    async def capture(
        self,
        session: AsyncSession,
        *,
        snapshot_id: UUID,
        horizon_seconds: int,
        due_at: datetime,
        observed_at: datetime,
    ) -> DecisionFutureOdds:
        existing = await session.scalar(
            select(DecisionFutureOdds).where(
                DecisionFutureOdds.decision_snapshot_id == snapshot_id,
                DecisionFutureOdds.capture_type == FutureOddsCaptureType.TIME_HORIZON,
                DecisionFutureOdds.horizon_seconds == horizon_seconds,
                DecisionFutureOdds.due_at == due_at,
            )
        )
        if existing is not None and existing.status == "CAPTURED":
            return existing
        snapshot = await session.get(DecisionSnapshotRecord, snapshot_id)
        if snapshot is None:
            raise ValueError("decision snapshot does not exist")
        observations = snapshot.canonical_payload.get("market", {}).get("observations", [])
        odds_ids = [item.get("odds_id") for item in observations if isinstance(item, dict)]
        captured: list[OddsObservationRecord] = []
        for odds_id in odds_ids:
            if not isinstance(odds_id, int):
                continue
            observation = await session.scalar(
                select(OddsObservationRecord)
                .where(
                    OddsObservationRecord.odds_id == odds_id,
                    OddsObservationRecord.received_at >= due_at,
                    OddsObservationRecord.received_at <= observed_at,
                )
                .order_by(OddsObservationRecord.received_at)
                .limit(1)
            )
            if observation is not None:
                captured.append(observation)
        captured.sort(key=lambda item: odds_ids.index(item.odds_id))
        quality_reference_at = (
            max(item.received_at for item in captured) if captured else observed_at
        )
        quality = _closing_pair_quality(
            snapshot,
            captured,
            triggered_at=quality_reference_at,
            max_age_seconds=self._market_max_age_seconds,
            max_pair_skew_seconds=self._market_max_pair_skew_seconds,
        )
        complete = quality is not None and quality.eligible
        status = (
            captured[0].normalized_status
            if complete and captured[0].normalized_status == captured[1].normalized_status
            else "UNKNOWN"
        )
        values = {
            "triggered_at": due_at,
            "observed_at": max(item.received_at for item in captured) if complete else observed_at,
            "odds_a": captured[0].price if complete else None,
            "odds_b": captured[1].price if complete else None,
            "market_type": _market_value(snapshot, "market_type"),
            "match_stage": _market_value(snapshot, "match_stage"),
            "market_status": status,
            "capture_policy_version": "time-horizon-v2-pair-validated",
            "pair_quality": (
                quality.model_dump(mode="json")
                if quality is not None
                else {
                    "eligible": False,
                    "blockers": ["MARKET_PAIR_IDENTITY_INVALID"],
                    "warnings": [],
                }
            ),
            "pair_skew_seconds": quality.pair_skew_seconds if quality is not None else None,
            "status": "CAPTURED" if complete else "MISSING",
        }
        if existing is None:
            record = DecisionFutureOdds(
                decision_snapshot_id=snapshot_id,
                capture_type=FutureOddsCaptureType.TIME_HORIZON,
                horizon_seconds=horizon_seconds,
                due_at=due_at,
                **values,
            )
            session.add(record)
        else:
            record = existing
            for field, value in values.items():
                setattr(record, field, value)
        await session.flush()
        return record

    async def capture_closing(
        self,
        session: AsyncSession,
        *,
        snapshot_id: UUID,
        triggered_at: datetime,
    ) -> DecisionFutureOdds:
        existing = await session.scalar(
            select(DecisionFutureOdds).where(
                DecisionFutureOdds.decision_snapshot_id == snapshot_id,
                DecisionFutureOdds.capture_type == FutureOddsCaptureType.CLOSING,
            )
        )
        if existing is not None and existing.status == "CAPTURED":
            return existing
        snapshot = await session.get(DecisionSnapshotRecord, snapshot_id)
        if snapshot is None:
            raise ValueError("decision snapshot does not exist")
        market = snapshot.canonical_payload.get("market", {})
        observations = market.get("observations", []) if isinstance(market, dict) else []
        odds_ids = [item.get("odds_id") for item in observations if isinstance(item, dict)]
        provider_match_id = market.get("provider_match_id") if isinstance(market, dict) else None
        market_type = market.get("market_type") if isinstance(market, dict) else None
        match_stage = market.get("match_stage") if isinstance(market, dict) else None
        captured: list[OddsObservationRecord] = []
        for odds_id in odds_ids:
            if not isinstance(odds_id, int):
                continue
            observation = await session.scalar(
                select(OddsObservationRecord)
                .where(
                    OddsObservationRecord.odds_id == odds_id,
                    OddsObservationRecord.provider_match_id == provider_match_id,
                    OddsObservationRecord.market_type == market_type,
                    OddsObservationRecord.match_stage == match_stage,
                    OddsObservationRecord.received_at <= triggered_at,
                )
                .order_by(OddsObservationRecord.received_at.desc())
                .limit(1)
            )
            if observation is not None:
                captured.append(observation)
        captured.sort(key=lambda item: odds_ids.index(item.odds_id))
        quality = _closing_pair_quality(
            snapshot,
            captured,
            triggered_at=triggered_at,
            max_age_seconds=self._market_max_age_seconds,
            max_pair_skew_seconds=self._market_max_pair_skew_seconds,
        )
        complete = quality is not None and quality.eligible
        status = (
            captured[0].normalized_status
            if complete and captured[0].normalized_status == captured[1].normalized_status
            else "UNKNOWN"
        )
        values = {
            "triggered_at": triggered_at,
            "observed_at": max(item.received_at for item in captured) if complete else triggered_at,
            "odds_a": captured[0].price if complete else None,
            "odds_b": captured[1].price if complete else None,
            "market_type": market_type if isinstance(market_type, str) else None,
            "match_stage": match_stage if isinstance(match_stage, str) else None,
            "market_status": status,
            "capture_policy_version": CLOSING_POLICY_VERSION,
            "pair_quality": (
                quality.model_dump(mode="json")
                if quality is not None
                else {
                    "eligible": False,
                    "blockers": ["MARKET_PAIR_IDENTITY_INVALID"],
                    "warnings": [],
                }
            ),
            "pair_skew_seconds": quality.pair_skew_seconds if quality is not None else None,
            "status": "CAPTURED" if complete else "MISSING",
        }
        if existing is None:
            record = DecisionFutureOdds(
                decision_snapshot_id=snapshot_id,
                capture_type=FutureOddsCaptureType.CLOSING,
                horizon_seconds=None,
                due_at=triggered_at,
                **values,
            )
            session.add(record)
        else:
            record = existing
            for field, value in values.items():
                setattr(record, field, value)
        await session.flush()
        return record


def _market_value(snapshot: DecisionSnapshotRecord, field: str) -> str | None:
    value = snapshot.canonical_payload.get("market", {}).get(field)
    return value if isinstance(value, str) else None


def _market_status(snapshot: DecisionSnapshotRecord) -> str:
    value = snapshot.canonical_payload.get("market", {}).get("quality", {}).get("warnings")
    return "UNKNOWN" if value else "OPEN_CONFIRMED"


def _closing_pair_quality(
    snapshot: DecisionSnapshotRecord,
    captured: list[OddsObservationRecord],
    *,
    triggered_at: datetime,
    max_age_seconds: float,
    max_pair_skew_seconds: float,
):
    identity = snapshot.canonical_payload.get("identity", {})
    if not isinstance(identity, dict):
        return None
    try:
        series_id = UUID(str(identity["series_id"]))
        map_id = UUID(str(identity["map_id"])) if identity.get("map_id") else None
        team_ids = frozenset(
            (
                UUID(str(identity["team_a"]["id"])),
                UUID(str(identity["team_b"]["id"])),
            )
        )
    except KeyError, TypeError, ValueError:
        return None
    legs = tuple(
        MarketPairLeg(
            provider_match_id=item.provider_match_id,
            odds_id=item.odds_id,
            canonical_series_id=item.canonical_series_id,
            canonical_map_id=item.canonical_map_id,
            market_type=item.market_type,
            match_stage=item.match_stage,
            selection_team_id=item.selection_team_id,
            price=item.price,
            normalized_status=item.normalized_status,
            metadata_version=item.metadata_version,
            received_at=item.received_at,
        )
        for item in captured
    )
    return evaluate_market_pair(
        legs,
        expected_series_id=series_id,
        expected_map_id=map_id,
        expected_team_ids=team_ids,
        decision_at=triggered_at,
        max_age_seconds=max_age_seconds,
        max_pair_skew_seconds=max_pair_skew_seconds,
    )
