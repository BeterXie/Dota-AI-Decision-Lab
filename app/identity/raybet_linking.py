from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.identity import ProviderMatch
from app.identity.aliases import equivalent_team_aliases
from app.identity.resolver import IdentityAmbiguousError
from app.models import (
    CanonicalEvent,
    CanonicalMap,
    CanonicalSeries,
    OddsObservationRecord,
    ProviderEventMapping,
    ProviderMatchMapping,
    ProviderTeamMapping,
    TeamAlias,
)


@dataclass(frozen=True, slots=True)
class RayBetLinkResult:
    canonical_series_id: UUID | None
    fallback_allowed: bool
    reason: str


class RayBetExistingSeriesLinker:
    """Safely attach RayBet identity to a Liquipedia-backed canonical series.

    The linker runs before the legacy RayBet identity fallback. It can explicitly
    block that fallback when Liquipedia evidence exists but conflicts, preventing
    a later resolver from guessing across tournaments or BO formats.
    """

    def __init__(self, *, start_time_window: timedelta = timedelta(hours=3)) -> None:
        self._start_time_window = start_time_window

    async def link(self, session: AsyncSession, match: ProviderMatch) -> RayBetLinkResult:
        existing = await self._raybet_match_mapping(session, match)
        existing_series_id = existing.canonical_series_id if existing is not None else None
        if existing is not None and existing_series_id is not None:
            if existing.resolved_by != "PROVIDER_DISCOVERY":
                return RayBetLinkResult(existing_series_id, False, "existing_canonical_mapping")
            if existing.canonical_map_id is not None or await self._series_has_maps(
                session, existing_series_id
            ):
                return RayBetLinkResult(existing_series_id, False, "fallback_has_downstream_maps")

        if match.scheduled_at is None:
            return RayBetLinkResult(
                existing_series_id,
                existing_series_id is None,
                "missing_schedule",
            )

        team_a_id = await self._existing_team_identity(
            session,
            provider_team_id=str(match.team_a_id),
            name=match.team_a_name,
        )
        team_b_id = await self._existing_team_identity(
            session,
            provider_team_id=str(match.team_b_id),
            name=match.team_b_name,
        )
        if team_a_id is None or team_b_id is None:
            return RayBetLinkResult(
                existing_series_id,
                existing_series_id is None,
                "team_identity_missing",
            )
        if team_a_id == team_b_id:
            raise IdentityAmbiguousError("RAYBET_EXISTING_SERIES_SAME_TEAM")

        candidates = await self._liquipedia_series_candidates(
            session,
            team_a_id=team_a_id,
            team_b_id=team_b_id,
            scheduled_at=match.scheduled_at,
        )
        if not candidates:
            return RayBetLinkResult(
                existing_series_id,
                existing_series_id is None,
                "no_liquipedia_candidate",
            )

        best_of = _parse_best_of(match.round)
        if best_of is not None:
            compatible = [
                candidate
                for candidate in candidates
                if candidate.best_of is None or candidate.best_of == best_of
            ]
            if not compatible:
                return RayBetLinkResult(existing_series_id, False, "best_of_conflict")
            candidates = compatible

        event_mapping = await self._raybet_event_mapping(session, match)
        if event_mapping is not None and await self._event_is_liquipedia_backed(
            session, event_mapping.canonical_event_id
        ):
            candidates = [
                candidate
                for candidate in candidates
                if candidate.event_id == event_mapping.canonical_event_id
            ]
            if not candidates:
                return RayBetLinkResult(existing_series_id, False, "event_mapping_conflict")
        elif match.tournament_name:
            candidates = await self._filter_by_event_name(
                session,
                candidates,
                match.tournament_name,
            )
            if not candidates:
                return RayBetLinkResult(existing_series_id, False, "event_name_conflict")

        if len(candidates) > 1:
            raise IdentityAmbiguousError("RAYBET_EXISTING_SERIES_AMBIGUOUS")

        series = candidates[0]
        reconciled = existing_series_id is not None and existing_series_id != series.id
        await self._attach_event_mapping(session, match, series)
        exact_best_of = best_of is not None and series.best_of == best_of
        if series.best_of is None:
            series.best_of = best_of
        if series.scheduled_at is None:
            series.scheduled_at = match.scheduled_at

        prefix = "LIQUIPEDIA_RECONCILED" if reconciled else "LIQUIPEDIA"
        resolved_by = f"{prefix}_TEAMS_TIME_BO" if exact_best_of else f"{prefix}_TEAMS_TIME"
        confidence = 0.99 if exact_best_of else 0.97

        if existing is None:
            session.add(
                ProviderMatchMapping(
                    provider="raybet",
                    provider_match_id=str(match.provider_match_id),
                    canonical_series_id=series.id,
                    resolved_by=resolved_by,
                    confidence=confidence,
                )
            )
        else:
            previous_series_id = existing.canonical_series_id
            existing.canonical_series_id = series.id
            existing.resolved_by = resolved_by
            existing.confidence = confidence
            if previous_series_id is not None and previous_series_id != series.id:
                await session.execute(
                    update(OddsObservationRecord)
                    .where(
                        OddsObservationRecord.provider_match_id == match.provider_match_id,
                        OddsObservationRecord.canonical_series_id == previous_series_id,
                        OddsObservationRecord.canonical_map_id.is_(None),
                    )
                    .values(canonical_series_id=series.id)
                )

        return RayBetLinkResult(
            series.id,
            False,
            "reconciled_liquipedia_series" if reconciled else "matched_liquipedia_series",
        )

    async def _raybet_match_mapping(
        self,
        session: AsyncSession,
        match: ProviderMatch,
    ) -> ProviderMatchMapping | None:
        return await session.scalar(
            select(ProviderMatchMapping).where(
                ProviderMatchMapping.provider == "raybet",
                ProviderMatchMapping.provider_match_id == str(match.provider_match_id),
            )
        )

    async def _series_has_maps(self, session: AsyncSession, series_id: UUID) -> bool:
        return (
            await session.scalar(
                select(CanonicalMap.id).where(CanonicalMap.series_id == series_id).limit(1)
            )
            is not None
        )

    async def _existing_team_identity(
        self,
        session: AsyncSession,
        *,
        provider_team_id: str,
        name: str,
    ) -> UUID | None:
        mapping = await session.scalar(
            select(ProviderTeamMapping).where(
                ProviderTeamMapping.provider == "raybet",
                ProviderTeamMapping.provider_team_id == provider_team_id,
            )
        )
        if mapping is not None:
            return mapping.canonical_team_id

        aliases = equivalent_team_aliases(name)
        candidates = list(
            (
                await session.scalars(
                    select(TeamAlias).where(TeamAlias.normalized_name.in_(aliases))
                )
            ).all()
        )
        candidate_ids = {candidate.canonical_team_id for candidate in candidates}
        if len(candidate_ids) > 1:
            raise IdentityAmbiguousError("RAYBET_TEAM_IDENTITY_AMBIGUOUS")
        if not candidate_ids:
            return None

        canonical_team_id = next(iter(candidate_ids))
        session.add(
            ProviderTeamMapping(
                provider="raybet",
                provider_team_id=provider_team_id,
                canonical_team_id=canonical_team_id,
                observed_name=name,
            )
        )
        return canonical_team_id

    async def _liquipedia_series_candidates(
        self,
        session: AsyncSession,
        *,
        team_a_id: UUID,
        team_b_id: UUID,
        scheduled_at,
    ) -> list[CanonicalSeries]:
        liquipedia_mapping_exists = (
            select(ProviderMatchMapping.id)
            .where(
                ProviderMatchMapping.provider == "liquipedia",
                ProviderMatchMapping.canonical_series_id == CanonicalSeries.id,
            )
            .exists()
        )
        statement = select(CanonicalSeries).where(
            liquipedia_mapping_exists,
            or_(
                and_(
                    CanonicalSeries.team_a_id == team_a_id,
                    CanonicalSeries.team_b_id == team_b_id,
                ),
                and_(
                    CanonicalSeries.team_a_id == team_b_id,
                    CanonicalSeries.team_b_id == team_a_id,
                ),
            ),
            CanonicalSeries.scheduled_at.is_not(None),
            CanonicalSeries.scheduled_at >= scheduled_at - self._start_time_window,
            CanonicalSeries.scheduled_at <= scheduled_at + self._start_time_window,
        )
        return list((await session.scalars(statement)).all())

    async def _raybet_event_mapping(
        self,
        session: AsyncSession,
        match: ProviderMatch,
    ) -> ProviderEventMapping | None:
        if match.tournament_id is None:
            return None
        return await session.scalar(
            select(ProviderEventMapping).where(
                ProviderEventMapping.provider == "raybet",
                ProviderEventMapping.provider_event_id == str(match.tournament_id),
            )
        )

    async def _event_is_liquipedia_backed(
        self,
        session: AsyncSession,
        event_id: UUID,
    ) -> bool:
        return (
            await session.scalar(
                select(ProviderEventMapping.id)
                .where(
                    ProviderEventMapping.provider == "liquipedia",
                    ProviderEventMapping.canonical_event_id == event_id,
                )
                .limit(1)
            )
            is not None
        )

    async def _filter_by_event_name(
        self,
        session: AsyncSession,
        candidates: list[CanonicalSeries],
        event_name: str,
    ) -> list[CanonicalSeries]:
        event_ids = {
            candidate.event_id for candidate in candidates if candidate.event_id is not None
        }
        if not event_ids:
            return []
        events = list(
            (
                await session.scalars(
                    select(CanonicalEvent).where(CanonicalEvent.id.in_(event_ids))
                )
            ).all()
        )
        compatible_ids = {
            event.id for event in events if _event_names_compatible(event_name, event.name)
        }
        return [candidate for candidate in candidates if candidate.event_id in compatible_ids]

    async def _attach_event_mapping(
        self,
        session: AsyncSession,
        match: ProviderMatch,
        series: CanonicalSeries,
    ) -> None:
        if match.tournament_id is None or series.event_id is None:
            return
        provider_event_id = str(match.tournament_id)
        mapping = await session.scalar(
            select(ProviderEventMapping).where(
                ProviderEventMapping.provider == "raybet",
                ProviderEventMapping.provider_event_id == provider_event_id,
            )
        )
        if mapping is None:
            session.add(
                ProviderEventMapping(
                    provider="raybet",
                    provider_event_id=provider_event_id,
                    canonical_event_id=series.event_id,
                )
            )
            return
        if mapping.canonical_event_id == series.event_id:
            return
        if await self._event_is_liquipedia_backed(session, mapping.canonical_event_id):
            raise IdentityAmbiguousError("RAYBET_EVENT_SERIES_CONFLICT")
        mapping.canonical_event_id = series.event_id


def _parse_best_of(value: str | None) -> int | None:
    if value is None:
        return None
    normalized = value.casefold().strip()
    if normalized.startswith("bo") and normalized[2:].isdigit():
        return int(normalized[2:])
    return None


def _event_names_compatible(first: str, second: str) -> bool:
    return bool(_event_name_keys(first) & _event_name_keys(second))


def _event_name_keys(value: str) -> frozenset[str]:
    tokens = re.findall(r"[a-z0-9]+", value.casefold())
    if not tokens:
        return frozenset()
    numbers = [token for token in tokens if token.isdigit()]
    words = [token for token in tokens if not token.isdigit()]
    without_articles = [token for token in words if token not in {"a", "an", "the"}]
    keys = {" ".join(tokens), "".join(tokens)}
    if without_articles:
        keys.add(" ".join([*without_articles, *numbers]))
        keys.add("".join([*without_articles, *numbers]))
    if len(words) >= 2:
        acronym = "".join(token[0] for token in words)
        keys.add(" ".join([acronym, *numbers]))
        keys.add("".join([acronym, *numbers]))
    if len(without_articles) >= 2:
        acronym = "".join(token[0] for token in without_articles)
        keys.add(" ".join([acronym, *numbers]))
        keys.add("".join([acronym, *numbers]))
    return frozenset(key for key in keys if key)
