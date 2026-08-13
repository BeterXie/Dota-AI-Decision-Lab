from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.canonical import content_digest
from app.domain.draft import DraftCurve, DraftDerivedFeatures, DraftMinutePoint
from app.draft.engine import MODEL_VERSION, score_rosh_lineups
from app.draft.features import build_draft_curve
from app.models import (
    DraftMinuteCurveRecord,
    DraftSlotRecord,
    DraftSnapshotRecord,
    FeatureSnapshotSource,
)
from app.providers.stratz.client import StratzClient
from app.providers.stratz.draft_queries import (
    QUERY_VERSION,
    WEEK_SECONDS,
    build_player_highlights_query,
    build_rosh_query_requests,
    normalize_player_highlights_response,
    normalize_rosh_analysis,
)
from app.repositories.raw import RawEventRepository


class RoshService:
    def __init__(self, client: StratzClient, raw_events: RawEventRepository) -> None:
        self._client = client
        self._raw_events = raw_events

    async def build(
        self,
        session: AsyncSession,
        *,
        canonical_map_id: UUID,
        draft_snapshot_id: UUID,
        current_minute: int | None = None,
    ) -> DraftCurve:
        snapshot = await session.get(DraftSnapshotRecord, draft_snapshot_id)
        if snapshot is None or snapshot.canonical_map_id != canonical_map_id:
            raise ValueError("draft snapshot does not belong to the canonical map")
        if not snapshot.complete:
            raise ValueError("DRAFT_PARTIAL")
        existing = await session.scalar(
            select(DraftMinuteCurveRecord).where(
                DraftMinuteCurveRecord.draft_snapshot_id == draft_snapshot_id,
                DraftMinuteCurveRecord.model_version == MODEL_VERSION,
            )
        )
        if existing is not None:
            return _curve_from_record(existing)
        slots = list(
            (
                await session.scalars(
                    select(DraftSlotRecord).where(
                        DraftSlotRecord.draft_snapshot_id == draft_snapshot_id
                    )
                )
            ).all()
        )
        radiant, dire = _ordered_slots(slots)
        ordered_slots = [*radiant, *dire]
        hero_ids = [slot.hero_id for slot in ordered_slots if slot.hero_id is not None]
        if len(hero_ids) != 10:
            raise ValueError("DRAFT_PARTIAL")
        cutoff = snapshot.statistics_cutoff
        raw_source_ids: list[UUID] = []
        analysis, requests, statistics_week = await self._load_analysis(
            session,
            canonical_map_id=canonical_map_id,
            hero_ids=hero_ids,
            cutoff=cutoff,
            raw_source_ids=raw_source_ids,
        )

        synergy_request = requests["synergy"]
        synergy_response = await self._client.execute(
            operation_name=synergy_request["operation_name"],
            query=synergy_request["query"],
            variables=synergy_request["variables"],
        )
        raw_source_ids.append(
            await self._archive_response(
                session,
                key="synergy",
                request=synergy_request,
                response=synergy_response,
                provider_key=f"{canonical_map_id}:{statistics_week}",
            )
        )
        if not synergy_response.payload.get("errors"):
            analysis["synergy"] = normalize_rosh_analysis(
                {"synergy": synergy_response.payload}
            )["synergy"]

        players = [
            {"steamAccountId": slot.account_id, "heroId": hero_id}
            for slot, hero_id in zip(ordered_slots, hero_ids, strict=True)
        ]
        highlight_request = build_player_highlights_query(players)
        highlights: dict[int, dict | None] = {}
        if highlight_request["query"]:
            response = await self._client.execute(
                operation_name=highlight_request["operation_name"],
                query=highlight_request["query"],
                variables=highlight_request["variables"],
            )
            raw_source_ids.append(
                await self._archive_response(
                    session,
                    key="player_highlights",
                    request=highlight_request,
                    response=response,
                    provider_key=str(canonical_map_id),
                )
            )
            # GraphQL may return usable `data.plus` entries alongside errors for
            # anonymous accounts. Preserve the usable entries and expose the
            # unresolved slots through player_analysis instead of discarding all
            # ten results.
            highlights = normalize_player_highlights_response(
                highlight_request, response.payload
            )
        radiant_highlights = [highlights.get(index) for index in range(5)]
        dire_highlights = [highlights.get(index) for index in range(5, 10)]
        slot_statuses = [
            {
                "selected": slot.account_id is not None,
                "fallback_reason": highlight_request["fallback_reasons"].get(index),
            }
            for index, slot in enumerate(ordered_slots)
        ]
        result = score_rosh_lineups(
            hero_ids[:5],
            hero_ids[5:],
            analysis,
            radiant_player_highlights=radiant_highlights,
            dire_player_highlights=dire_highlights,
            player_slot_statuses=slot_statuses,
        )
        if not result["pure_minute_table"]:
            raise ValueError("STRATZ_ROSH_STATISTICS_UNAVAILABLE")
        data_version = content_digest(
            {
                "analysis": analysis,
                "highlights": highlights,
                "cutoff": cutoff,
                "statistics_week": statistics_week,
            }
        )
        curve = build_draft_curve(
            result,
            current_minute=current_minute,
            statistics_cutoff=cutoff,
            data_version=data_version,
        )
        record = DraftMinuteCurveRecord(
            canonical_map_id=canonical_map_id,
            draft_snapshot_id=draft_snapshot_id,
            points=[point.model_dump(mode="json") for point in curve.points],
            derived_features={
                **curve.features.model_dump(mode="json"),
                "pure_lineup_score": result["pure_lineup_score"],
                "player_adjusted_lineup_score": result["player_adjusted_lineup_score"],
                "player_analysis": result["player_analysis"],
                "used_player_adjustment": result["used_player_adjustment"],
                "fell_back_to_pure_score": result["fell_back_to_pure_score"],
                "reference": result["reference"],
                "query_version": QUERY_VERSION,
                "statistics_week": statistics_week,
            },
            statistics_cutoff=cutoff,
            model_version=curve.model_version,
            data_version=data_version,
        )
        session.add(record)
        await session.flush()
        for raw_id in raw_source_ids:
            session.add(
                FeatureSnapshotSource(
                    feature_type="DRAFT_MINUTE_CURVE",
                    feature_snapshot_id=record.id,
                    provider="stratz",
                    provider_match_id=str(canonical_map_id),
                    raw_event_id=raw_id,
                    first_usable_at=cutoff,
                )
            )
        return curve

    async def _load_analysis(
        self,
        session: AsyncSession,
        *,
        canonical_map_id: UUID,
        hero_ids: Sequence[int],
        cutoff,
        raw_source_ids: list[UUID],
    ) -> tuple[dict[str, dict], dict[str, dict], int]:
        """Load the newest usable STRATZ statistics week at or before cutoff.

        STRATZ can return an empty current-week window during the provider's
        weekly roll-over. The empty response is valid raw evidence, but it is
        not a usable Draft Intelligence input. Try prior completed weeks while
        preserving every raw response for provenance.
        """
        cutoff_week = int(cutoff.timestamp())
        for weeks_back in range(5):
            statistics_week = cutoff_week - (weeks_back * WEEK_SECONDS)
            requests = build_rosh_query_requests(hero_ids, statistics_week)
            analysis_responses: dict[str, dict] = {}
            for key in ("heroes_meta_positions", "hero_stats_by_time_bracket"):
                request = requests[key]
                response = await self._client.execute(
                    operation_name=request["operation_name"],
                    query=request["query"],
                    variables=request["variables"],
                )
                raw_source_ids.append(
                    await self._archive_response(
                        session,
                        key=f"{key}_week_{statistics_week}",
                        request=request,
                        response=response,
                        provider_key=f"{canonical_map_id}:{statistics_week}",
                    )
                )
                analysis_responses[key] = response.payload
            analysis = normalize_rosh_analysis(analysis_responses)
            if _has_usable_rosh_statistics(analysis):
                return analysis, requests, statistics_week
        raise ValueError("STRATZ_ROSH_STATISTICS_UNAVAILABLE")

    async def _archive_response(
        self,
        session: AsyncSession,
        *,
        key: str,
        request: dict,
        response,
        provider_key: str,
    ) -> UUID:
        payload = {
            "request": {
                "operation_name": request["operation_name"],
                "variables": request["variables"],
                "query_version": QUERY_VERSION,
            },
            "response": response.payload,
        }
        return await self._raw_events.append(
            session,
            provider="stratz",
            event_type=f"STRATZ_ROSH_{key.upper()}",
            provider_key=provider_key,
            payload=payload,
            request_started_at=response.request_started_at,
            received_at=response.received_at,
            parser_version=QUERY_VERSION,
        )


def _curve_from_record(record: DraftMinuteCurveRecord) -> DraftCurve:
    return DraftCurve(
        points=tuple(DraftMinutePoint.model_validate(point) for point in record.points),
        features=DraftDerivedFeatures.model_validate(record.derived_features),
        statistics_cutoff=record.statistics_cutoff,
        model_version=record.model_version,
        data_version=record.data_version,
    )


def _has_usable_rosh_statistics(analysis: dict[str, dict]) -> bool:
    meta = analysis.get("heroes_meta_positions", {})
    by_time = analysis.get("hero_stats_by_time_bracket", {})
    meta_rows = sum(
        len(meta.get(f"heroesPos_{position}", []))
        for position in range(1, 6)
        if isinstance(meta.get(f"heroesPos_{position}"), list)
    )
    time_rows = sum(
        len(by_time.get(f"heroStatsByTime_{position}", []))
        for position in range(1, 6)
        if isinstance(by_time.get(f"heroStatsByTime_{position}"), list)
    )
    return meta_rows > 0 and time_rows > 0


def _ordered_slots(
    slots: Sequence[DraftSlotRecord],
) -> tuple[list[DraftSlotRecord], list[DraftSlotRecord]]:
    radiant = sorted((slot for slot in slots if slot.side == "radiant"), key=lambda s: s.position)
    dire = sorted((slot for slot in slots if slot.side == "dire"), key=lambda s: s.position)
    expected_positions = list(range(1, 6))
    if (
        len(slots) != 10
        or [slot.position for slot in radiant] != expected_positions
        or [slot.position for slot in dire] != expected_positions
    ):
        raise ValueError("DRAFT_PARTIAL")
    return radiant, dire
