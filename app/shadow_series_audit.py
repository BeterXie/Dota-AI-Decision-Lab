from collections import Counter
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CanonicalMap, CanonicalSeries
from app.shadow_audit import build_shadow_run_audit


async def build_shadow_series_audit(
    session: AsyncSession,
    *,
    canonical_series_id: UUID,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    generated_at = generated_at or datetime.now(UTC)
    series = await session.get(CanonicalSeries, canonical_series_id)
    if series is None:
        raise ValueError("canonical series does not exist")
    maps = list(
        (
            await session.scalars(
                select(CanonicalMap)
                .where(CanonicalMap.series_id == canonical_series_id)
                .order_by(CanonicalMap.map_number, CanonicalMap.created_at)
            )
        ).all()
    )
    map_reports = [
        await build_shadow_run_audit(
            session,
            canonical_map_id=canonical_map.id,
            generated_at=generated_at,
        )
        for canonical_map in maps
    ]
    check_counts: Counter[str] = Counter()
    for report in map_reports:
        check_counts.update(report["check_status_counts"])
    return {
        "schema_version": "shadow-series-audit-v1",
        "generated_at": generated_at.isoformat(),
        "canonical_series_id": str(series.id),
        "best_of": series.best_of,
        "map_count": len(map_reports),
        "check_status_counts": dict(check_counts),
        "maps": map_reports,
    }
