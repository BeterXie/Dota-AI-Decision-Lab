from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CanonicalMap, CanonicalSeries, ProviderRawEvent, ProviderTeamMapping


@dataclass(frozen=True)
class DltvSideEvidence:
    radiant_provider_team_id: int | None
    dire_provider_team_id: int | None
    source: str | None
    confidence: float | None

    @property
    def resolved(self) -> bool:
        return self.radiant_provider_team_id is not None and self.dire_provider_team_id is not None


@dataclass(frozen=True)
class MapSideAssignment:
    status: str
    radiant_team_id: UUID | None
    dire_team_id: UUID | None
    source: str | None
    confidence: float | None
    observed_at: datetime | None
    raw_event_id: UUID | None
    blocker: str | None = None

    @property
    def resolved(self) -> bool:
        return self.status == "RESOLVED"


def parse_side_evidence(payload: dict[str, Any]) -> DltvSideEvidence:
    database = payload.get("db")
    if not isinstance(database, dict):
        return _unresolved_evidence()
    first_team = database.get("first_team")
    second_team = database.get("second_team")
    if not isinstance(first_team, dict) or not isinstance(second_team, dict):
        return _unresolved_evidence()
    first_id = _team_id(first_team)
    second_id = _team_id(second_team)
    first_is_radiant = first_team.get("is_radiant")
    second_is_radiant = second_team.get("is_radiant")
    if (
        first_id is None
        or second_id is None
        or not isinstance(first_is_radiant, bool)
        or not isinstance(second_is_radiant, bool)
        or first_is_radiant == second_is_radiant
    ):
        return _unresolved_evidence()
    if first_is_radiant:
        radiant_id, dire_id = first_id, second_id
    else:
        radiant_id, dire_id = second_id, first_id
    return DltvSideEvidence(
        radiant_provider_team_id=radiant_id,
        dire_provider_team_id=dire_id,
        source="DLTV_DB_IS_RADIANT",
        confidence=1.0,
    )


async def project_map_sides(
    session: AsyncSession,
    *,
    canonical_map: CanonicalMap,
    series: CanonicalSeries,
    as_of: datetime | None = None,
) -> MapSideAssignment:
    if canonical_map.valve_match_id is None:
        return _unresolved_assignment("SIDE_IDENTITY_VALVE_MATCH_MISSING")
    criteria = [
        ProviderRawEvent.provider == "dltv",
        ProviderRawEvent.event_type == "DLTV_BOOTSTRAP",
        ProviderRawEvent.provider_key == str(canonical_map.valve_match_id),
    ]
    if as_of is not None:
        criteria.append(ProviderRawEvent.received_at <= as_of)
    raw = await session.scalar(
        select(ProviderRawEvent)
        .where(*criteria)
        .order_by(ProviderRawEvent.received_at.desc())
        .limit(1)
    )
    if raw is None:
        return _unresolved_assignment("SIDE_IDENTITY_EVIDENCE_MISSING")
    evidence = parse_side_evidence(raw.payload)
    if not evidence.resolved:
        return MapSideAssignment(
            status="UNRESOLVED",
            radiant_team_id=None,
            dire_team_id=None,
            source=None,
            confidence=None,
            observed_at=raw.received_at,
            raw_event_id=raw.id,
            blocker="SIDE_IDENTITY_UNRESOLVED",
        )
    provider_ids = {
        str(evidence.radiant_provider_team_id),
        str(evidence.dire_provider_team_id),
    }
    mappings = list(
        (
            await session.scalars(
                select(ProviderTeamMapping).where(
                    ProviderTeamMapping.provider == "dltv",
                    ProviderTeamMapping.provider_team_id.in_(provider_ids),
                )
            )
        ).all()
    )
    canonical_by_provider = {
        mapping.provider_team_id: mapping.canonical_team_id for mapping in mappings
    }
    radiant_team_id = canonical_by_provider.get(str(evidence.radiant_provider_team_id))
    dire_team_id = canonical_by_provider.get(str(evidence.dire_provider_team_id))
    if radiant_team_id is None or dire_team_id is None:
        return MapSideAssignment(
            status="UNRESOLVED",
            radiant_team_id=None,
            dire_team_id=None,
            source=evidence.source,
            confidence=evidence.confidence,
            observed_at=raw.received_at,
            raw_event_id=raw.id,
            blocker="SIDE_IDENTITY_TEAM_MAPPING_MISSING",
        )
    expected = {series.team_a_id, series.team_b_id}
    actual = {radiant_team_id, dire_team_id}
    if radiant_team_id == dire_team_id or actual != expected:
        return MapSideAssignment(
            status="CONFLICT",
            radiant_team_id=radiant_team_id,
            dire_team_id=dire_team_id,
            source=evidence.source,
            confidence=evidence.confidence,
            observed_at=raw.received_at,
            raw_event_id=raw.id,
            blocker="SIDE_IDENTITY_SERIES_CONFLICT",
        )
    return MapSideAssignment(
        status="RESOLVED",
        radiant_team_id=radiant_team_id,
        dire_team_id=dire_team_id,
        source=evidence.source,
        confidence=evidence.confidence,
        observed_at=raw.received_at,
        raw_event_id=raw.id,
    )


def side_assignment_payload(assignment: MapSideAssignment) -> dict[str, object]:
    return {
        "status": assignment.status,
        "radiant_team_id": (
            str(assignment.radiant_team_id) if assignment.radiant_team_id is not None else None
        ),
        "dire_team_id": str(assignment.dire_team_id) if assignment.dire_team_id is not None else None,
        "source": assignment.source,
        "confidence": assignment.confidence,
        "observed_at": assignment.observed_at,
        "raw_event_id": str(assignment.raw_event_id) if assignment.raw_event_id is not None else None,
        "blocker": assignment.blocker,
    }


def _team_id(team: dict[str, Any]) -> int | None:
    value = team.get("id")
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _unresolved_evidence() -> DltvSideEvidence:
    return DltvSideEvidence(
        radiant_provider_team_id=None,
        dire_provider_team_id=None,
        source=None,
        confidence=None,
    )


def _unresolved_assignment(blocker: str) -> MapSideAssignment:
    return MapSideAssignment(
        status="UNRESOLVED",
        radiant_team_id=None,
        dire_team_id=None,
        source=None,
        confidence=None,
        observed_at=None,
        raw_event_id=None,
        blocker=blocker,
    )
