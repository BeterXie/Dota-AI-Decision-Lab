from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.competition import classify_stage
from app.identity.aliases import equivalent_team_aliases, normalize_alias
from app.identity.resolver import IdentityAmbiguousError
from app.models import (
    CanonicalEvent,
    CanonicalSeries,
    CanonicalTeam,
    ProviderEventMapping,
    ProviderMatchMapping,
    ProviderTeamMapping,
    TeamAlias,
)
from app.providers.liquipedia.models import (
    LiquipediaSeriesObservation,
    LiquipediaTournamentObservation,
)


@dataclass(frozen=True, slots=True)
class ProjectionResult:
    events_observed: int = 0
    series_observed: int = 0
    series_created: int = 0
    series_reused: int = 0
    series_skipped: int = 0


class LiquipediaCanonicalProjector:
    """Seed canonical event/series identity from deterministic Liquipedia observations."""

    def __init__(self, *, start_time_window: timedelta = timedelta(hours=3)) -> None:
        self._start_time_window = start_time_window

    async def project_tournaments(
        self,
        session: AsyncSession,
        observations: list[LiquipediaTournamentObservation],
    ) -> ProjectionResult:
        for observation in observations:
            await self._resolve_event(
                session,
                provider_event_id=observation.page_name,
                name=observation.name,
            )
        return ProjectionResult(events_observed=len(observations))

    async def project_series(
        self,
        session: AsyncSession,
        observations: list[LiquipediaSeriesObservation],
    ) -> ProjectionResult:
        created = 0
        reused = 0
        skipped = 0
        for observation in observations:
            outcome = await self._project_one_series(session, observation)
            if outcome == "created":
                created += 1
            elif outcome == "reused":
                reused += 1
            else:
                skipped += 1
        return ProjectionResult(
            series_observed=len(observations),
            series_created=created,
            series_reused=reused,
            series_skipped=skipped,
        )

    async def _project_one_series(
        self,
        session: AsyncSession,
        observation: LiquipediaSeriesObservation,
    ) -> str:
        if (
            observation.tournament_page is None
            or observation.tournament_name is None
            or observation.team_a_page is None
            or observation.team_b_page is None
            or observation.scheduled_at is None
        ):
            return "skipped"

        existing_mapping = await session.scalar(
            select(ProviderMatchMapping).where(
                ProviderMatchMapping.provider == "liquipedia",
                ProviderMatchMapping.provider_match_id == observation.provider_key,
            )
        )
        if existing_mapping is not None and existing_mapping.canonical_series_id is not None:
            series = await session.get(CanonicalSeries, existing_mapping.canonical_series_id)
            if series is None:
                raise ValueError("Liquipedia match mapping references a missing canonical series")
            event_id = await self._resolve_event(
                session,
                provider_event_id=observation.tournament_page,
                name=observation.tournament_name,
                canonical_event_id=series.event_id,
            )
            if series.event_id is None:
                series.event_id = event_id
            _apply_schedule(series, observation)
            return "reused"

        team_a_id = await self._resolve_team(
            session,
            provider_team_id=observation.team_a_page,
            name=observation.team_a_name,
        )
        team_b_id = await self._resolve_team(
            session,
            provider_team_id=observation.team_b_page,
            name=observation.team_b_name,
        )
        if team_a_id == team_b_id:
            raise IdentityAmbiguousError("LIQUIPEDIA_SERIES_SAME_TEAM")

        event_mapping = await session.scalar(
            select(ProviderEventMapping).where(
                ProviderEventMapping.provider == "liquipedia",
                ProviderEventMapping.provider_event_id == observation.tournament_page,
            )
        )
        candidates = await self._series_candidates(
            session,
            event_id=(event_mapping.canonical_event_id if event_mapping is not None else None),
            team_a_id=team_a_id,
            team_b_id=team_b_id,
            scheduled_at=observation.scheduled_at,
            best_of=observation.best_of,
        )
        if len(candidates) > 1:
            raise IdentityAmbiguousError("LIQUIPEDIA_SERIES_AMBIGUOUS")
        if candidates:
            series = candidates[0]
            event_id = await self._resolve_event(
                session,
                provider_event_id=observation.tournament_page,
                name=observation.tournament_name,
                canonical_event_id=series.event_id,
            )
            if series.event_id is None:
                series.event_id = event_id
            _apply_schedule(series, observation)
            outcome = "reused"
        else:
            event_id = await self._resolve_event(
                session,
                provider_event_id=observation.tournament_page,
                name=observation.tournament_name,
            )
            series = CanonicalSeries(
                event_id=event_id,
                team_a_id=team_a_id,
                team_b_id=team_b_id,
                best_of=observation.best_of,
                stage_key=classify_stage(observation.stage),
                scheduled_at=observation.scheduled_at,
            )
            session.add(series)
            await session.flush()
            outcome = "created"

        session.add(
            ProviderMatchMapping(
                provider="liquipedia",
                provider_match_id=observation.provider_key,
                canonical_series_id=series.id,
                resolved_by="LIQUIPEDIA_SCHEDULE",
                confidence=0.95,
            )
        )
        return outcome

    async def _resolve_event(
        self,
        session: AsyncSession,
        *,
        provider_event_id: str,
        name: str,
        canonical_event_id: UUID | None = None,
    ) -> UUID:
        mapping = await session.scalar(
            select(ProviderEventMapping).where(
                ProviderEventMapping.provider == "liquipedia",
                ProviderEventMapping.provider_event_id == provider_event_id,
            )
        )
        if mapping is not None:
            if canonical_event_id is not None and mapping.canonical_event_id != canonical_event_id:
                raise IdentityAmbiguousError("LIQUIPEDIA_EVENT_IDENTITY_CONFLICT")
            event = await session.get(CanonicalEvent, mapping.canonical_event_id)
            if event is None:
                raise ValueError("Liquipedia event mapping references a missing canonical event")
            event.name = name
            return mapping.canonical_event_id

        if canonical_event_id is not None:
            event = await session.get(CanonicalEvent, canonical_event_id)
            if event is None:
                raise ValueError("canonical series references a missing event")
            event.name = name
        else:
            same_name = list(
                (
                    await session.scalars(select(CanonicalEvent).where(CanonicalEvent.name == name))
                ).all()
            )
            if len(same_name) > 1:
                raise IdentityAmbiguousError("LIQUIPEDIA_EVENT_NAME_AMBIGUOUS")
            if same_name:
                event = same_name[0]
            else:
                event = CanonicalEvent(name=name)
                session.add(event)
                await session.flush()
        session.add(
            ProviderEventMapping(
                provider="liquipedia",
                provider_event_id=provider_event_id,
                canonical_event_id=event.id,
            )
        )
        return event.id

    async def _resolve_team(
        self,
        session: AsyncSession,
        *,
        provider_team_id: str,
        name: str,
    ) -> UUID:
        mapping = await session.scalar(
            select(ProviderTeamMapping).where(
                ProviderTeamMapping.provider == "liquipedia",
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
            raise IdentityAmbiguousError("LIQUIPEDIA_TEAM_IDENTITY_AMBIGUOUS")
        if candidate_ids:
            canonical_team_id = next(iter(candidate_ids))
        else:
            team = CanonicalTeam(name=name)
            session.add(team)
            await session.flush()
            canonical_team_id = team.id
            session.add(
                TeamAlias(
                    canonical_team_id=team.id,
                    name=name,
                    normalized_name=normalize_alias(name),
                    provider="liquipedia",
                )
            )
        session.add(
            ProviderTeamMapping(
                provider="liquipedia",
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
        event_id: UUID | None,
        team_a_id: UUID,
        team_b_id: UUID,
        scheduled_at,
        best_of: int | None,
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
        )
        if event_id is not None:
            statement = statement.where(CanonicalSeries.event_id == event_id)
        if scheduled_at is not None:
            statement = statement.where(
                CanonicalSeries.scheduled_at.is_not(None),
                CanonicalSeries.scheduled_at >= scheduled_at - self._start_time_window,
                CanonicalSeries.scheduled_at <= scheduled_at + self._start_time_window,
            )
        if best_of is not None:
            statement = statement.where(
                or_(CanonicalSeries.best_of.is_(None), CanonicalSeries.best_of == best_of)
            )
        return list((await session.scalars(statement)).all())


def _apply_schedule(series: CanonicalSeries, observation: LiquipediaSeriesObservation) -> None:
    if observation.best_of is not None:
        series.best_of = observation.best_of
    if observation.stage is not None:
        series.stage_key = classify_stage(observation.stage)
    if observation.scheduled_at is not None:
        series.scheduled_at = observation.scheduled_at
