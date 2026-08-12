import asyncio
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
        requests = build_rosh_query_requests(hero_ids, int(cutoff.timestamp()))
        response_items = await asyncio.gather(
            *(
                self._client.execute(
                    operation_name=request["operation_name"],
                    query=request["query"],
                    variables=request["variables"],
                )
                for request in requests.values()
            )
        )
        responses: dict[str, dict] = {}
        raw_source_ids: list[UUID] = []
        for (key, request), response in zip(requests.items(), response_items, strict=True):
            raw_id = await self._archive_response(
                session,
                key=key,
                request=request,
                response=response,
                provider_key=str(canonical_map_id),
            )
            raw_source_ids.append(raw_id)
            if response.payload.get("errors"):
                raise ValueError(f"STRATZ GraphQL error for {key}")
            responses[key] = response.payload
        analysis = normalize_rosh_analysis(responses)

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
            if not response.payload.get("errors"):
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
        data_version = content_digest(
            {"responses": responses, "highlights": highlights, "cutoff": cutoff}
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
