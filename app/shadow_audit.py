from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    CanonicalMap,
    DecisionSnapshotRecord,
    DomainEventRecord,
    OddsObservationRecord,
    ProviderMatchMapping,
    ProviderRawEvent,
)
from app.shadow_audit_lifecycle import ai_report
from app.shadow_audit_snapshot import live_freshness, snapshot_quality, temporal_alignment


async def build_shadow_run_audit(
    session: AsyncSession,
    *,
    canonical_map_id: UUID,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    generated_at = generated_at or datetime.now(UTC)
    canonical_map = await session.get(CanonicalMap, canonical_map_id)
    if canonical_map is None:
        raise ValueError("canonical map does not exist")
    snapshots = list(
        (
            await session.scalars(
                select(DecisionSnapshotRecord)
                .where(DecisionSnapshotRecord.canonical_map_id == canonical_map_id)
                .order_by(DecisionSnapshotRecord.decision_at)
            )
        ).all()
    )
    provider_evidence, dltv_raw = await _provider_evidence(session, canonical_map)
    reconnect = _reconnect_report(
        dltv_raw,
        await _recovery_events(session, canonical_map),
    )
    side = _side_identity(snapshots)
    freshness = live_freshness(snapshots)
    snapshot_summary = snapshot_quality(snapshots)
    ai = await ai_report(session, snapshots)
    checks = _integrity_checks(side, reconnect, freshness, snapshot_summary, ai)
    return {
        "schema_version": "shadow-run-audit-v1",
        "generated_at": generated_at.isoformat(),
        "map": {
            "canonical_map_id": str(canonical_map.id),
            "canonical_series_id": str(canonical_map.series_id) if canonical_map.series_id else None,
            "map_number": canonical_map.map_number,
            "valve_match_id": canonical_map.valve_match_id,
        },
        "provider_evidence": provider_evidence,
        "side_identity": side,
        "dltv_reconnect": reconnect,
        "live_freshness": freshness,
        "temporal_alignment": await temporal_alignment(session, canonical_map.id),
        "snapshots": snapshot_summary,
        "ai": ai,
        "checks": checks,
        "check_status_counts": dict(Counter(item["status"] for item in checks)),
    }


async def _provider_evidence(
    session: AsyncSession, canonical_map: CanonicalMap
) -> tuple[dict[str, Any], list[ProviderRawEvent]]:
    mapping = await session.scalar(
        select(ProviderMatchMapping)
        .where(
            ProviderMatchMapping.provider == "raybet",
            or_(
                ProviderMatchMapping.canonical_map_id == canonical_map.id,
                ProviderMatchMapping.canonical_series_id == canonical_map.series_id,
            ),
        )
        .order_by(ProviderMatchMapping.created_at.desc())
        .limit(1)
    )
    raybet_id = mapping.provider_match_id if mapping is not None else None
    dltv_raw = await _raw_events(
        session,
        provider="dltv",
        keys=_dltv_keys(canonical_map.valve_match_id),
    )
    raybet_raw = await _raw_events(
        session,
        provider="raybet",
        keys=(str(raybet_id),) if raybet_id else (),
    )
    odds_count = len(
        list(
            (
                await session.scalars(
                    select(OddsObservationRecord.id).where(
                        OddsObservationRecord.canonical_map_id == canonical_map.id
                    )
                )
            ).all()
        )
    )
    return (
        {
            "raybet": {
                "provider_match_id": raybet_id,
                "raw_event_count": len(raybet_raw),
                "map_odds_observation_count": odds_count,
            },
            "dltv": {
                "raw_event_count": len(dltv_raw),
                "socket_event_count": sum(
                    item.event_type == "DLTV_FAST_SOCKET" for item in dltv_raw
                ),
                "bootstrap_event_count": sum(
                    item.event_type == "DLTV_BOOTSTRAP" for item in dltv_raw
                ),
                "duplicate_socket_event_count": sum(
                    item.event_type == "DLTV_FAST_SOCKET" and item.is_duplicate is True
                    for item in dltv_raw
                ),
            },
        },
        dltv_raw,
    )


async def _raw_events(
    session: AsyncSession, *, provider: str, keys: tuple[str, ...]
) -> list[ProviderRawEvent]:
    if not keys:
        return []
    return list(
        (
            await session.scalars(
                select(ProviderRawEvent)
                .where(
                    ProviderRawEvent.provider == provider,
                    ProviderRawEvent.provider_key.in_(keys),
                )
                .order_by(ProviderRawEvent.received_at)
            )
        ).all()
    )


async def _recovery_events(
    session: AsyncSession, canonical_map: CanonicalMap
) -> list[DomainEventRecord]:
    if canonical_map.valve_match_id is None:
        return []
    events = list(
        (
            await session.scalars(
                select(DomainEventRecord).where(
                    DomainEventRecord.event_type == "DLTV_MATCH_DISCOVERED",
                    DomainEventRecord.aggregate_id == str(canonical_map.valve_match_id),
                )
            )
        ).all()
    )
    return [
        item
        for item in events
        if item.payload.get("reason") == "SOCKET_RECONNECT_RECOVERY"
    ]


def _reconnect_report(
    raw: list[ProviderRawEvent], recovery: list[DomainEventRecord]
) -> dict[str, Any]:
    connections: list[str] = []
    for item in raw:
        if item.event_type != "DLTV_FAST_SOCKET" or item.connection_id is None:
            continue
        if not connections or connections[-1] != item.connection_id:
            connections.append(item.connection_id)
    recovered = {
        item.payload.get("connection_id")
        for item in recovery
        if isinstance(item.payload.get("connection_id"), str)
    }
    transition_targets = set(connections[1:])
    return {
        "connection_sequence": connections,
        "connection_transitions": max(len(connections) - 1, 0),
        "recovery_event_count": len(recovery),
        "recovery_connection_ids": sorted(recovered),
        "uncovered_connection_transitions": len(transition_targets - recovered),
    }


def _side_identity(snapshots: list[DecisionSnapshotRecord]) -> dict[str, Any]:
    statuses: Counter[str] = Counter()
    pairs: set[tuple[str, str]] = set()
    latest = None
    for snapshot in snapshots:
        identity = snapshot.canonical_payload.get("identity", {})
        raw = identity.get("side_identity") if isinstance(identity, dict) else None
        if not isinstance(raw, dict):
            continue
        status = str(raw.get("status") or "UNKNOWN")
        statuses[status] += 1
        radiant = raw.get("radiant_team_id")
        dire = raw.get("dire_team_id")
        if status == "RESOLVED" and isinstance(radiant, str) and isinstance(dire, str):
            pairs.add((radiant, dire))
        latest = raw
    return {
        "status_counts": dict(statuses),
        "resolved_pair_count": len(pairs),
        "stable": len(pairs) <= 1 and statuses.get("CONFLICT", 0) == 0,
        "latest": latest,
    }


def _integrity_checks(
    side: dict[str, Any],
    reconnect: dict[str, Any],
    freshness: dict[str, Any],
    snapshots: dict[str, Any],
    ai: dict[str, Any],
) -> list[dict[str, str]]:
    live_count = int(snapshots["live_snapshot_count"])
    freshness_count = int(freshness["snapshot_count_with_field_evidence"])
    return [
        {
            "name": "side_identity_stable",
            "status": "PASS" if side["stable"] else "FAIL",
        },
        {
            "name": "dltv_reconnect_recovery",
            "status": (
                "PASS"
                if reconnect["uncovered_connection_transitions"] == 0
                else "WARN"
            ),
        },
        {
            "name": "live_field_freshness_evidence",
            "status": (
                "NOT_APPLICABLE"
                if live_count == 0
                else "PASS" if freshness_count >= live_count else "WARN"
            ),
        },
        {
            "name": "ai_snapshot_hash_alignment",
            "status": (
                "PASS" if ai["snapshot_hash_mismatch_count"] == 0 else "FAIL"
            ),
        },
    ]


def _dltv_keys(valve_match_id: int | None) -> tuple[str, ...]:
    if valve_match_id is None:
        return ()
    return (f"__nd2_match_{valve_match_id}", str(valve_match_id))
