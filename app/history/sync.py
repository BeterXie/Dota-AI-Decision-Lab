import asyncio
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.history.repository import HistoricalRepository
from app.models import ProviderTeamMapping
from app.providers.history import HistoricalProvider
from app.providers.opendota.client import OpenDotaClient
from app.providers.stratz.history_queries import team_match_ids
from app.repositories.raw import RawEventRepository


@dataclass(frozen=True)
class HistoricalSyncResult:
    provider: str
    maps_requested: int
    maps_fetched: int
    maps_normalized: int
    maps_canonicalized: int
    maps_eligible_team_rating: int
    maps_advanced_ready: int
    identity_missing_count: int
    provider_fallback_count: int
    conflict_count: int
    warnings: tuple[str, ...]


class HistoricalSyncService:
    def __init__(
        self,
        *,
        primary: HistoricalProvider | None,
        fallback: OpenDotaClient,
        raw_events: RawEventRepository,
        repository: HistoricalRepository,
        concurrency: int,
    ) -> None:
        if concurrency <= 0:
            raise ValueError("historical fetch concurrency must be positive")
        self._primary = primary
        self._fallback = fallback
        self._raw_events = raw_events
        self._repository = repository
        self._concurrency = concurrency

    async def sync_team(
        self,
        session: AsyncSession,
        *,
        canonical_team_id: UUID,
        before: datetime,
        limit: int,
    ) -> HistoricalSyncResult:
        list_provider: HistoricalProvider = self._primary or self._fallback
        warnings: list[str] = []
        primary_identity_missing = False
        provider_team_id = await self._provider_team_id(
            session,
            provider=list_provider.name,
            canonical_team_id=canonical_team_id,
        )
        if provider_team_id is None and list_provider is not self._fallback:
            primary_identity_missing = True
            warnings.append("HISTORICAL_PRIMARY_TEAM_IDENTITY_MISSING")
            list_provider = self._fallback
            provider_team_id = await self._provider_team_id(
                session,
                provider=self._fallback.name,
                canonical_team_id=canonical_team_id,
            )
        if provider_team_id is None:
            raise ValueError("HISTORICAL_TEAM_IDENTITY_MISSING")
        try:
            response = await list_provider.get_team_pro_maps(
                provider_team_id, before=before, limit=limit
            )
            await self._archive(
                session,
                provider=list_provider,
                event_type="HISTORICAL_TEAM_MAPS",
                provider_key=provider_team_id,
                response=response,
            )
            match_ids = _match_ids(list_provider.name, response.payload, before, limit)
        except Exception as primary_error:
            if list_provider is self._fallback:
                raise
            list_provider = self._fallback
            fallback_team_id = await self._provider_team_id(
                session,
                provider=self._fallback.name,
                canonical_team_id=canonical_team_id,
            )
            if fallback_team_id is None:
                raise ValueError("HISTORICAL_FALLBACK_TEAM_IDENTITY_MISSING") from primary_error
            provider_team_id = fallback_team_id
            response = await self._fallback.get_team_pro_maps(
                provider_team_id, before=before, limit=limit
            )
            await self._archive(
                session,
                provider=self._fallback,
                event_type="HISTORICAL_TEAM_MAPS",
                provider_key=provider_team_id,
                response=response,
            )
            match_ids = _match_ids("opendota", response.payload, before, limit)

        semaphore = asyncio.Semaphore(self._concurrency)

        async def fetch(match_id: int):
            async with semaphore:
                return await self._fetch_match(
                    match_id,
                    allow_primary=not primary_identity_missing,
                )

        fetched = await asyncio.gather(*(fetch(match_id) for match_id in match_ids))
        persisted = 0
        fallback_count = 0
        normalized = 0
        canonicalized = 0
        eligible_team_rating = 0
        advanced_ready = 0
        identity_missing = 0
        conflict_count = 0
        for match_id, (provider, response, primary_error) in zip(match_ids, fetched, strict=True):
            if primary_error is not None:
                warnings.append(f"STRATZ_FALLBACK:{primary_error}")
            raw_event_id = await self._archive(
                session,
                provider=provider,
                event_type="HISTORICAL_MATCH",
                provider_key=str(match_id),
                response=response,
            )
            if not isinstance(response.payload, dict):
                warnings.append("HISTORICAL_MATCH_PAYLOAD_INVALID")
                continue
            bundle = provider.normalize_match(response.payload, fetched_at=response.received_at)
            normalized += 1
            fact = await self._repository.persist_bundle(
                session,
                bundle,
                raw_event_id=raw_event_id,
                normalizer_version=provider.normalizer_version,
            )
            persisted += 1
            canonical_teams = int(fact.radiant_team_id is not None) + int(
                fact.dire_team_id is not None
            )
            canonicalized += int(canonical_teams == 2)
            eligible_team_rating += int(canonical_teams == 2 and fact.winner_team_id is not None)
            identity_missing += int(canonical_teams < 2)
            advanced_ready += int(bundle.advanced_available)
            conflict_count += int(fact.sync_status == "DATA_CONFLICT")
            fallback_count += int(provider is self._fallback and self._primary is not None)
            warnings.extend(bundle.warnings)
        return HistoricalSyncResult(
            provider=list_provider.name,
            maps_requested=len(match_ids),
            maps_fetched=len(fetched),
            maps_normalized=normalized,
            maps_canonicalized=canonicalized,
            maps_eligible_team_rating=eligible_team_rating,
            maps_advanced_ready=advanced_ready,
            identity_missing_count=identity_missing,
            provider_fallback_count=fallback_count,
            conflict_count=conflict_count,
            warnings=tuple(dict.fromkeys(warnings)),
        )

    async def _fetch_match(self, match_id: int, *, allow_primary: bool = True):
        primary_error: str | None = None
        if self._primary is not None and allow_primary:
            try:
                response = await self._primary.get_match_advanced(match_id)
                if not isinstance(response.payload, dict) or response.payload.get("errors"):
                    raise ValueError("STRATZ GraphQL match response contains errors")
                return self._primary, response, None
            except Exception as exc:
                primary_error = f"{type(exc).__name__}: {exc}"
        try:
            response = await self._fallback.get_match_advanced(match_id)
        except Exception as fallback_error:
            raise RuntimeError(
                f"historical providers failed for match {match_id}; "
                f"primary={primary_error}; fallback={type(fallback_error).__name__}: "
                f"{fallback_error}"
            ) from fallback_error
        return self._fallback, response, primary_error

    async def _archive(
        self,
        session: AsyncSession,
        *,
        provider: HistoricalProvider,
        event_type: str,
        provider_key: str,
        response,
    ) -> UUID:
        payload = response.payload
        archived = {"items": payload} if isinstance(payload, list) else payload
        return await self._raw_events.append(
            session,
            provider=provider.name,
            event_type=event_type,
            provider_key=provider_key,
            payload=archived,
            request_started_at=response.request_started_at,
            received_at=response.received_at,
            parser_version=provider.normalizer_version,
        )

    async def _provider_team_id(
        self,
        session: AsyncSession,
        *,
        provider: str,
        canonical_team_id: UUID,
    ) -> str | None:
        return await session.scalar(
            select(ProviderTeamMapping.provider_team_id).where(
                ProviderTeamMapping.provider == provider,
                ProviderTeamMapping.canonical_team_id == canonical_team_id,
            )
        )


def _match_ids(provider: str, payload: dict | list, before: datetime, limit: int) -> list[int]:
    if provider == "stratz":
        if not isinstance(payload, dict):
            raise ValueError("STRATZ team match response must be an object")
        if payload.get("errors"):
            raise ValueError("STRATZ GraphQL team response contains errors")
        return team_match_ids(payload, before=before, limit=limit)
    if not isinstance(payload, dict) or not isinstance(payload.get("matches"), list):
        raise ValueError("OpenDota team match response is invalid")
    result: list[int] = []
    for item in payload["matches"]:
        if isinstance(item, dict) and isinstance(item.get("match_id"), int):
            result.append(item["match_id"])
        if len(result) >= limit:
            break
    return result
