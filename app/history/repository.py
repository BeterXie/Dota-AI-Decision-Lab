from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.history import HistoricalMatchBundle, PlayerHistoricalMap
from app.models import (
    CanonicalEvent,
    CanonicalHero,
    CanonicalMap,
    CanonicalPlayer,
    CanonicalSeries,
    CanonicalTeam,
    HistoricalMapRecord,
    HistoricalPlayerMapRecord,
    ProviderEventMapping,
    ProviderHeroMapping,
    ProviderMatchMapping,
    ProviderPlayerMapping,
    ProviderTeamMapping,
)
from app.time import earliest


class HistoricalRepository:
    async def persist_bundle(
        self,
        session: AsyncSession,
        bundle: HistoricalMatchBundle,
        *,
        raw_event_id: UUID,
        normalizer_version: str,
    ) -> HistoricalMapRecord:
        provider = bundle.match.provider
        radiant_team_id = await self._team_id(session, provider, bundle.match.radiant_team_id)
        dire_team_id = await self._team_id(session, provider, bundle.match.dire_team_id)
        winner_team_id = await self._team_id(session, provider, bundle.match.winner_team_id)
        canonical_map = await self._canonical_map(
            session,
            bundle=bundle,
            radiant_team_id=radiant_team_id,
            dire_team_id=dire_team_id,
        )
        record = await session.scalar(
            select(HistoricalMapRecord).where(
                HistoricalMapRecord.provider == provider,
                HistoricalMapRecord.provider_match_id == bundle.match.provider_match_id,
            )
        )
        status = "ADVANCED_READY" if bundle.advanced_available else "BASIC_READY"
        if record is None:
            record = HistoricalMapRecord(
                canonical_map_id=canonical_map.id if canonical_map is not None else None,
                provider=provider,
                provider_match_id=bundle.match.provider_match_id,
                patch_id=bundle.match.patch_id,
                started_at=bundle.match.started_at,
                ended_at=bundle.match.ended_at,
                radiant_team_id=radiant_team_id,
                dire_team_id=dire_team_id,
                winner_team_id=winner_team_id,
                first_usable_at=bundle.match.first_usable_at,
                fetched_at=bundle.match.fetched_at,
                normalizer_version=normalizer_version,
                basic_ready_at=bundle.match.first_usable_at,
                advanced_ready_at=(
                    bundle.match.first_usable_at if bundle.advanced_available else None
                ),
                sync_status=status,
                raw_event_id=raw_event_id,
            )
            session.add(record)
            await session.flush()
        else:
            if (
                record.winner_team_id is not None
                and winner_team_id is not None
                and record.winner_team_id != winner_team_id
            ):
                record.sync_status = "DATA_CONFLICT"
            record.canonical_map_id = record.canonical_map_id or (
                canonical_map.id if canonical_map is not None else None
            )
            record.radiant_team_id = record.radiant_team_id or radiant_team_id
            record.dire_team_id = record.dire_team_id or dire_team_id
            record.winner_team_id = record.winner_team_id or winner_team_id
            record.patch_id = record.patch_id or bundle.match.patch_id
            record.ended_at = record.ended_at or bundle.match.ended_at
            record.first_usable_at = earliest(record.first_usable_at, bundle.match.first_usable_at)
            record.fetched_at = bundle.match.fetched_at
            record.normalizer_version = normalizer_version
            record.raw_event_id = raw_event_id
            if bundle.advanced_available and record.advanced_ready_at is None:
                record.advanced_ready_at = bundle.match.first_usable_at
            if record.sync_status != "DATA_CONFLICT":
                record.sync_status = (
                    "ADVANCED_READY" if record.advanced_ready_at is not None else "BASIC_READY"
                )

        for player in bundle.players:
            await self._persist_player(
                session,
                historical_map=record,
                player=player,
                provider=provider,
                advanced=bundle.advanced_available,
            )
        await self._flag_cross_provider_conflict(session, record)
        return record

    async def _canonical_map(
        self,
        session: AsyncSession,
        *,
        bundle: HistoricalMatchBundle,
        radiant_team_id: UUID | None,
        dire_team_id: UUID | None,
    ) -> CanonicalMap | None:
        try:
            valve_match_id = int(bundle.match.provider_match_id)
        except ValueError:
            return None
        canonical_map = await session.scalar(
            select(CanonicalMap).where(CanonicalMap.valve_match_id == valve_match_id)
        )
        if canonical_map is not None:
            await self._ensure_match_mapping(
                session,
                provider=bundle.match.provider,
                provider_match_id=bundle.match.provider_match_id,
                canonical_map=canonical_map,
                valve_match_id=valve_match_id,
            )
            return canonical_map
        if radiant_team_id is None or dire_team_id is None:
            return None
        event_id = await self._event_id(session, bundle)
        series = CanonicalSeries(
            event_id=event_id,
            team_a_id=radiant_team_id,
            team_b_id=dire_team_id,
            scheduled_at=bundle.match.started_at,
        )
        session.add(series)
        await session.flush()
        canonical_map = CanonicalMap(
            series_id=series.id,
            map_number=1,
            valve_match_id=valve_match_id,
            scheduled_at=bundle.match.started_at,
        )
        session.add(canonical_map)
        await session.flush()
        await self._ensure_match_mapping(
            session,
            provider=bundle.match.provider,
            provider_match_id=bundle.match.provider_match_id,
            canonical_map=canonical_map,
            valve_match_id=valve_match_id,
        )
        return canonical_map

    async def _ensure_match_mapping(
        self,
        session: AsyncSession,
        *,
        provider: str,
        provider_match_id: str,
        canonical_map: CanonicalMap,
        valve_match_id: int,
    ) -> None:
        mapping = await session.scalar(
            select(ProviderMatchMapping).where(
                ProviderMatchMapping.provider == provider,
                ProviderMatchMapping.provider_match_id == provider_match_id,
            )
        )
        if mapping is None:
            session.add(
                ProviderMatchMapping(
                    provider=provider,
                    provider_match_id=provider_match_id,
                    canonical_series_id=canonical_map.series_id,
                    canonical_map_id=canonical_map.id,
                    valve_match_id=valve_match_id,
                    resolved_by="VALVE_MATCH_ID",
                    confidence=1.0,
                )
            )
            return
        mapping.canonical_series_id = canonical_map.series_id
        mapping.canonical_map_id = canonical_map.id
        mapping.valve_match_id = valve_match_id

    async def _event_id(self, session: AsyncSession, bundle: HistoricalMatchBundle) -> UUID | None:
        provider_event_id = bundle.match.event_id
        if provider_event_id is None:
            return None
        mapping = await session.scalar(
            select(ProviderEventMapping).where(
                ProviderEventMapping.provider == bundle.match.provider,
                ProviderEventMapping.provider_event_id == provider_event_id,
            )
        )
        if mapping is not None:
            return mapping.canonical_event_id
        event = CanonicalEvent(
            name=bundle.match.event_name or f"{bundle.match.provider}:{provider_event_id}"
        )
        session.add(event)
        await session.flush()
        session.add(
            ProviderEventMapping(
                provider=bundle.match.provider,
                provider_event_id=provider_event_id,
                canonical_event_id=event.id,
            )
        )
        return event.id

    async def _persist_player(
        self,
        session: AsyncSession,
        *,
        historical_map: HistoricalMapRecord,
        player: PlayerHistoricalMap,
        provider: str,
        advanced: bool,
    ) -> None:
        canonical_player_id = await self._player_id(session, provider, player.account_id)
        await self._hero_id(session, provider, player.hero_id)
        canonical_team_id = await self._team_id(session, provider, player.team_id)
        opponent_team_id = await self._team_id(session, provider, player.opponent_team_id)
        record = await session.scalar(
            select(HistoricalPlayerMapRecord).where(
                HistoricalPlayerMapRecord.historical_map_id == historical_map.id,
                HistoricalPlayerMapRecord.account_id == player.account_id,
            )
        )
        if record is None:
            session.add(
                HistoricalPlayerMapRecord(
                    historical_map_id=historical_map.id,
                    canonical_player_id=canonical_player_id,
                    account_id=player.account_id,
                    canonical_team_id=canonical_team_id,
                    opponent_team_id=opponent_team_id,
                    hero_id=player.hero_id,
                    position=player.position,
                    won=player.won,
                    kills=player.kills,
                    deaths=player.deaths,
                    assists=player.assists,
                    gpm=player.gpm,
                    xpm=player.xpm,
                    networth=player.networth,
                    last_hits=player.last_hits,
                    hero_damage=player.hero_damage,
                    tower_damage=player.tower_damage,
                    impact=player.impact,
                    basic_first_usable_at=player.first_usable_at,
                    advanced_first_usable_at=(player.first_usable_at if advanced else None),
                )
            )
            return
        if record.won != player.won or record.hero_id != player.hero_id:
            historical_map.sync_status = "DATA_CONFLICT"
            return
        record.canonical_player_id = record.canonical_player_id or canonical_player_id
        record.canonical_team_id = record.canonical_team_id or canonical_team_id
        record.opponent_team_id = record.opponent_team_id or opponent_team_id
        record.position = record.position or player.position
        for field in (
            "kills",
            "deaths",
            "assists",
            "gpm",
            "xpm",
            "networth",
            "last_hits",
            "hero_damage",
            "tower_damage",
            "impact",
        ):
            value = getattr(player, field)
            if value is not None:
                setattr(record, field, value)
        if advanced and record.advanced_first_usable_at is None:
            record.advanced_first_usable_at = player.first_usable_at

    async def _flag_cross_provider_conflict(
        self, session: AsyncSession, record: HistoricalMapRecord
    ) -> None:
        if record.winner_team_id is None:
            return
        other = await session.scalar(
            select(HistoricalMapRecord).where(
                HistoricalMapRecord.provider != record.provider,
                HistoricalMapRecord.provider_match_id == record.provider_match_id,
                HistoricalMapRecord.winner_team_id.is_not(None),
            )
        )
        if other is not None and other.winner_team_id != record.winner_team_id:
            record.sync_status = "DATA_CONFLICT"
            other.sync_status = "DATA_CONFLICT"

    async def _team_id(
        self, session: AsyncSession, provider: str, provider_team_id: str | None
    ) -> UUID | None:
        if provider_team_id is None:
            return None
        existing = await session.scalar(
            select(ProviderTeamMapping.canonical_team_id).where(
                ProviderTeamMapping.provider == provider,
                ProviderTeamMapping.provider_team_id == provider_team_id,
            )
        )
        if existing is not None:
            return existing
        team = CanonicalTeam(name=f"{provider.upper()} team {provider_team_id}")
        session.add(team)
        await session.flush()
        session.add(
            ProviderTeamMapping(
                provider=provider,
                provider_team_id=provider_team_id,
                canonical_team_id=team.id,
            )
        )
        return team.id

    async def _player_id(self, session: AsyncSession, provider: str, account_id: int) -> UUID:
        mapping = await session.scalar(
            select(ProviderPlayerMapping).where(
                ProviderPlayerMapping.provider == provider,
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
                provider=provider,
                provider_player_id=str(account_id),
                canonical_player_id=player.id,
            )
        )
        return player.id

    async def _hero_id(self, session: AsyncSession, provider: str, hero_id: int) -> None:
        mapping = await session.scalar(
            select(ProviderHeroMapping).where(
                ProviderHeroMapping.provider == provider,
                ProviderHeroMapping.provider_hero_id == str(hero_id),
            )
        )
        if mapping is not None:
            return
        hero = await session.get(CanonicalHero, hero_id)
        if hero is None:
            session.add(CanonicalHero(hero_id=hero_id))
            await session.flush()
        session.add(
            ProviderHeroMapping(
                provider=provider,
                provider_hero_id=str(hero_id),
                canonical_hero_id=hero_id,
            )
        )
