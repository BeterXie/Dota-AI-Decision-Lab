from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.identity import ProviderMatch
from app.identity.aliases import equivalent_team_aliases
from app.identity.resolver import IdentityAmbiguousError
from app.models import (
    CanonicalEvent,
    CanonicalSeries,
    ProviderEventMapping,
    ProviderMatchMapping,
    ProviderTeamMapping,
    TeamAlias,
)


class RayBetExistingSeriesLinker:
    """Attach RayBet provider identity to an already-known canonical series.

    Liquipedia or another schedule source may create the canonical series before
    RayBet publishes odds. This linker reuses that identity when team/time
    evidence is unique. It never creates a canonical series; the existing
    IdentityResolver remains the fallback when no safe candidate exists.
    """

    def __init__(self, *, start_time_window: timedelta = timedelta(hours=3)) -> None:
        self._start_time_window = start_time_window

    async def link(self, session: AsyncSession, match: ProviderMatch) -> UUID | None:
        existing = await session.scalar(
            select(ProviderMatchMapping).where(
                ProviderMatchMapping.provider == "raybet",
                ProviderMatchMapping.provider_match_id == str(match.provider_match_id),
            )
        )
        if existing is not None:
            return existing.canonical_series_id
        if match.scheduled_at is None:
            return None

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
            return None
        if team_a_id == team_b_id:
            raise IdentityAmbiguousError("RAYBET_EXISTING_SERIES_SAME_TEAM")

        event_mapping = await self._raybet_event_mapping(session, match)
        candidates = await self._series_candidates(
            session,
            team_a_id=team_a_id,
            team_b_id=team_b_id,
            scheduled_at=match.scheduled_at,
        )
        best_of = _parse_best_of(match.round)
        if best_of is not None:
            candidates = [
                candidate
                for candidate in candidates
                if candidate.best_of is None or candidate.best_of == best_of
            ]
        if event_mapping is not None:
            candidates = [
                candidate
                for candidate in candidates
                if candidate.event_id == event_mapping.canonical_event_id
            ]
        elif len(candidates) > 1 and match.tournament_name:
            named = await self._filter_by_exact_event_name(
                session,
                candidates,
                match.tournament_name,
            )
            if named:
                candidates = named

        if len(candidates) > 1:
            raise IdentityAmbiguousError("RAYBET_EXISTING_SERIES_AMBIGUOUS")
        if not candidates:
            return None

        series = candidates[0]
        await self._attach_event_mapping(session, match, series)
        if series.best_of is None:
            series.best_of = best_of
        if series.scheduled_at is None:
            series.scheduled_at = match.scheduled_at
        session.add(
            ProviderMatchMapping(
                provider="raybet",
                provider_match_id=str(match.provider_match_id),
                canonical_series_id=series.id,
                resolved_by="EXISTING_CANONICAL_SERIES",
                confidence=0.95,
            )
        )
        return series.id

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

    async def _series_candidates(
        self,
        session: AsyncSession,
        *,
        team_a_id: UUID,
        team_b_id: UUID,
        scheduled_at,
    ) -> list[CanonicalSeries]:
        statement = select(CanonicalSeries).where(
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

    async def _filter_by_exact_event_name(
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
        matching_ids = set(
            (
                await session.scalars(
                    select(CanonicalEvent.id).where(
                        CanonicalEvent.id.in_(event_ids),
                        CanonicalEvent.name == event_name,
                    )
                )
            ).all()
        )
        return [candidate for candidate in candidates if candidate.event_id in matching_ids]

    async def _attach_event_mapping(
        self,
        session: AsyncSession,
        match: ProviderMatch,
        series: CanonicalSeries,
    ) -> None:
        if match.tournament_id is None:
            return
        provider_event_id = str(match.tournament_id)
        mapping = await session.scalar(
            select(ProviderEventMapping).where(
                ProviderEventMapping.provider == "raybet",
                ProviderEventMapping.provider_event_id == provider_event_id,
            )
        )
        if mapping is not None:
            if series.event_id is not None and mapping.canonical_event_id != series.event_id:
                raise IdentityAmbiguousError("RAYBET_EVENT_SERIES_CONFLICT")
            return

        if series.event_id is None:
            event = CanonicalEvent(name=match.tournament_name or f"raybet:{provider_event_id}")
            session.add(event)
            await session.flush()
            series.event_id = event.id
        session.add(
            ProviderEventMapping(
                provider="raybet",
                provider_event_id=provider_event_id,
                canonical_event_id=series.event_id,
            )
        )


def _parse_best_of(value: str | None) -> int | None:
    if value is None:
        return None
    normalized = value.casefold().strip()
    if normalized.startswith("bo") and normalized[2:].isdigit():
        return int(normalized[2:])
    return None
