from datetime import timedelta
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.identity import ProviderMatch
from app.identity.aliases import equivalent_team_aliases, normalize_alias
from app.models import (
    CanonicalEvent,
    CanonicalHero,
    CanonicalMap,
    CanonicalPlayer,
    CanonicalSeries,
    CanonicalTeam,
    ProviderEventMapping,
    ProviderHeroMapping,
    ProviderMatchMapping,
    ProviderPlayerMapping,
    ProviderTeamMapping,
    TeamAlias,
)
from app.providers.dltv.models import DltvBootstrapIdentity


class IdentityAmbiguousError(ValueError):
    pass


class ResolvedMap(BaseModel):
    model_config = ConfigDict(frozen=True)

    canonical_event_id: UUID | None
    canonical_series_id: UUID
    canonical_map_id: UUID
    team_a_id: UUID
    team_b_id: UUID
    radiant_team_id: UUID | None = None
    dire_team_id: UUID | None = None
    side_identity_source: str | None = None
    side_identity_confidence: float | None = None
    resolution_method: str


class IdentityResolver:
    def __init__(self, *, start_time_window: timedelta = timedelta(hours=3)) -> None:
        self._start_time_window = start_time_window

    async def observe_raybet_match(self, session: AsyncSession, match: ProviderMatch) -> UUID:
        existing = await self._match_mapping(session, "raybet", str(match.provider_match_id))
        if existing is not None and existing.canonical_series_id is not None:
            return existing.canonical_series_id
        team_a_id = await self._resolve_team(
            session,
            provider="raybet",
            provider_team_id=str(match.team_a_id),
            name=match.team_a_name,
        )
        team_b_id = await self._resolve_team(
            session,
            provider="raybet",
            provider_team_id=str(match.team_b_id),
            name=match.team_b_name,
        )
        event_id = await self._resolve_event(
            session,
            provider="raybet",
            provider_event_id=(
                str(match.tournament_id) if match.tournament_id is not None else None
            ),
            name=match.tournament_name,
        )
        series = CanonicalSeries(
            event_id=event_id,
            team_a_id=team_a_id,
            team_b_id=team_b_id,
            best_of=_parse_best_of(match.round),
            scheduled_at=match.scheduled_at,
        )
        session.add(series)
        await session.flush()
        session.add(
            ProviderMatchMapping(
                provider="raybet",
                provider_match_id=str(match.provider_match_id),
                canonical_series_id=series.id,
                resolved_by="PROVIDER_DISCOVERY",
                confidence=1.0,
            )
        )
        return series.id

    async def resolve_dltv_bootstrap(
        self,
        session: AsyncSession,
        identity: DltvBootstrapIdentity,
    ) -> ResolvedMap:
        first_team_id = await self._resolve_team(
            session,
            provider="dltv",
            provider_team_id=str(identity.first_team_id),
            name=identity.first_team_name,
        )
        second_team_id = await self._resolve_team(
            session,
            provider="dltv",
            provider_team_id=str(identity.second_team_id),
            name=identity.second_team_name,
        )
        radiant_team_id, dire_team_id = _canonical_sides(
            identity,
            first_team_id=first_team_id,
            second_team_id=second_team_id,
        )

        map_record = await session.scalar(
            select(CanonicalMap).where(CanonicalMap.valve_match_id == identity.valve_match_id)
        )
        if map_record is not None:
            series = await session.get(CanonicalSeries, map_record.series_id)
            if series is None:
                raise ValueError("canonical map references a missing series")
            _validate_series_teams(series, first_team_id, second_team_id)
            _validate_series_sides(series, radiant_team_id, dire_team_id)
            return ResolvedMap(
                canonical_event_id=series.event_id,
                canonical_series_id=series.id,
                canonical_map_id=map_record.id,
                team_a_id=series.team_a_id,
                team_b_id=series.team_b_id,
                radiant_team_id=radiant_team_id,
                dire_team_id=dire_team_id,
                side_identity_source=identity.side_identity_source,
                side_identity_confidence=identity.side_identity_confidence,
                resolution_method="VALVE_MATCH_ID",
            )

        event_id = await self._resolve_event(
            session,
            provider="dltv",
            provider_event_id=str(identity.event_id) if identity.event_id is not None else None,
            name=None,
        )
        candidates = await self._series_candidates(
            session,
            team_a_id=first_team_id,
            team_b_id=second_team_id,
            scheduled_at=identity.started_at,
        )
        if len(candidates) > 1:
            raise IdentityAmbiguousError("IDENTITY_AMBIGUOUS")
        if candidates:
            series = candidates[0]
            method = "CANONICAL_TEAMS_TIME"
        else:
            series = CanonicalSeries(
                event_id=event_id,
                team_a_id=first_team_id,
                team_b_id=second_team_id,
                scheduled_at=identity.started_at,
            )
            session.add(series)
            await session.flush()
            method = "DLTV_CANONICAL_CREATE"
        _validate_series_sides(series, radiant_team_id, dire_team_id)

        if identity.map_number is not None:
            existing_slot = await session.scalar(
                select(CanonicalMap).where(
                    CanonicalMap.series_id == series.id,
                    CanonicalMap.map_number == identity.map_number,
                )
            )
        else:
            existing_slot = None
        if existing_slot is not None:
            existing_slot.valve_match_id = identity.valve_match_id
            map_record = existing_slot
        else:
            map_record = CanonicalMap(
                series_id=series.id,
                map_number=identity.map_number,
                valve_match_id=identity.valve_match_id,
            )
            session.add(map_record)
            await session.flush()
        if identity.series_id is not None:
            mapping = await self._match_mapping(session, "dltv", str(identity.series_id))
            if mapping is None:
                session.add(
                    ProviderMatchMapping(
                        provider="dltv",
                        provider_match_id=str(identity.series_id),
                        canonical_series_id=series.id,
                        canonical_map_id=map_record.id,
                        valve_match_id=identity.valve_match_id,
                        resolved_by=method,
                        confidence=1.0,
                    )
                )
            else:
                mapping.canonical_series_id = series.id
                mapping.canonical_map_id = map_record.id
                mapping.valve_match_id = identity.valve_match_id
        return ResolvedMap(
            canonical_event_id=series.event_id,
            canonical_series_id=series.id,
            canonical_map_id=map_record.id,
            team_a_id=series.team_a_id,
            team_b_id=series.team_b_id,
            radiant_team_id=radiant_team_id,
            dire_team_id=dire_team_id,
            side_identity_source=identity.side_identity_source,
            side_identity_confidence=identity.side_identity_confidence,
            resolution_method=method,
        )

    async def resolve_dltv_player(self, session: AsyncSession, account_id: int) -> UUID:
        mapping = await session.scalar(
            select(ProviderPlayerMapping).where(
                ProviderPlayerMapping.provider == "dltv",
                ProviderPlayerMapping.provider_player_id == str(account_id),
            )
        )
        if mapping is not None:
            return mapping.canonical_player_id
        player = await session.scalar(
            select(CanonicalPlayer).where(CanonicalPlayer.account_id == account_id)
        )
        if player is None:
            player = CanonicalPlayer(account_id=account_id)
            session.add(player)
            await session.flush()
        session.add(
            ProviderPlayerMapping(
                provider="dltv",
                provider_player_id=str(account_id),
                canonical_player_id=player.id,
            )
        )
        return player.id

    async def resolve_dltv_hero(self, session: AsyncSession, hero_id: int) -> int:
        mapping = await session.scalar(
            select(ProviderHeroMapping).where(
                ProviderHeroMapping.provider == "dltv",
                ProviderHeroMapping.provider_hero_id == str(hero_id),
            )
        )
        if mapping is not None:
            return mapping.canonical_hero_id
        hero = await session.get(CanonicalHero, hero_id)
        if hero is None:
            hero = CanonicalHero(hero_id=hero_id)
            session.add(hero)
            await session.flush()
        session.add(
            ProviderHeroMapping(
                provider="dltv",
                provider_hero_id=str(hero_id),
                canonical_hero_id=hero_id,
            )
        )
        return hero_id

    async def _resolve_team(
        self,
        session: AsyncSession,
        *,
        provider: str,
        provider_team_id: str,
        name: str,
    ) -> UUID:
        mapping = await session.scalar(
            select(ProviderTeamMapping).where(
                ProviderTeamMapping.provider == provider,
                ProviderTeamMapping.provider_team_id == provider_team_id,
            )
        )
        if mapping is not None:
            return mapping.canonical_team_id
        normalized = normalize_alias(name)
        equivalent_aliases = equivalent_team_aliases(name)
        candidates = list(
            (
                await session.scalars(
                    select(TeamAlias).where(TeamAlias.normalized_name.in_(equivalent_aliases))
                )
            ).all()
        )
        candidate_ids = {candidate.canonical_team_id for candidate in candidates}
        if len(candidate_ids) > 1:
            raise IdentityAmbiguousError("TEAM_IDENTITY_AMBIGUOUS")
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
                    normalized_name=normalized,
                    provider=provider,
                )
            )
        session.add(
            ProviderTeamMapping(
                provider=provider,
                provider_team_id=provider_team_id,
                canonical_team_id=canonical_team_id,
                observed_name=name,
            )
        )
        return canonical_team_id

    async def _resolve_event(
        self,
        session: AsyncSession,
        *,
        provider: str,
        provider_event_id: str | None,
        name: str | None,
    ) -> UUID | None:
        if provider_event_id is None:
            return None
        mapping = await session.scalar(
            select(ProviderEventMapping).where(
                ProviderEventMapping.provider == provider,
                ProviderEventMapping.provider_event_id == provider_event_id,
            )
        )
        if mapping is not None:
            return mapping.canonical_event_id
        event = CanonicalEvent(name=name or f"{provider}:{provider_event_id}")
        session.add(event)
        await session.flush()
        session.add(
            ProviderEventMapping(
                provider=provider,
                provider_event_id=provider_event_id,
                canonical_event_id=event.id,
            )
        )
        return event.id

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
            )
        )
        if scheduled_at is not None:
            statement = statement.where(
                CanonicalSeries.scheduled_at.is_not(None),
                CanonicalSeries.scheduled_at >= scheduled_at - self._start_time_window,
                CanonicalSeries.scheduled_at <= scheduled_at + self._start_time_window,
            )
        return list((await session.scalars(statement)).all())

    async def _match_mapping(
        self, session: AsyncSession, provider: str, provider_match_id: str
    ) -> ProviderMatchMapping | None:
        return await session.scalar(
            select(ProviderMatchMapping).where(
                ProviderMatchMapping.provider == provider,
                ProviderMatchMapping.provider_match_id == provider_match_id,
            )
        )


def _canonical_sides(
    identity: DltvBootstrapIdentity,
    *,
    first_team_id: UUID,
    second_team_id: UUID,
) -> tuple[UUID | None, UUID | None]:
    radiant_provider_id = identity.radiant_provider_team_id
    dire_provider_id = identity.dire_provider_team_id
    if radiant_provider_id is None and dire_provider_id is None:
        return None, None
    if radiant_provider_id is None or dire_provider_id is None:
        raise IdentityAmbiguousError("SIDE_IDENTITY_PARTIAL")
    provider_to_canonical = {
        identity.first_team_id: first_team_id,
        identity.second_team_id: second_team_id,
    }
    if {radiant_provider_id, dire_provider_id} != set(provider_to_canonical):
        raise IdentityAmbiguousError("SIDE_IDENTITY_PROVIDER_CONFLICT")
    return provider_to_canonical[radiant_provider_id], provider_to_canonical[dire_provider_id]


def _validate_series_teams(
    series: CanonicalSeries, first_team_id: UUID, second_team_id: UUID
) -> None:
    if {series.team_a_id, series.team_b_id} != {first_team_id, second_team_id}:
        raise IdentityAmbiguousError("VALVE_MATCH_TEAM_CONFLICT")


def _validate_series_sides(
    series: CanonicalSeries,
    radiant_team_id: UUID | None,
    dire_team_id: UUID | None,
) -> None:
    if radiant_team_id is None and dire_team_id is None:
        return
    if radiant_team_id is None or dire_team_id is None:
        raise IdentityAmbiguousError("SIDE_IDENTITY_PARTIAL")
    if radiant_team_id == dire_team_id or {radiant_team_id, dire_team_id} != {
        series.team_a_id,
        series.team_b_id,
    }:
        raise IdentityAmbiguousError("SIDE_IDENTITY_SERIES_CONFLICT")


def _parse_best_of(value: str | None) -> int | None:
    if value is None:
        return None
    normalized = value.casefold().strip()
    if normalized.startswith("bo") and normalized[2:].isdigit():
        return int(normalized[2:])
    return None
