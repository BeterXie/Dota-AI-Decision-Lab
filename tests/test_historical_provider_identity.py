from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import Base
from app.history.identity import HistoricalTeamResolver
from app.history.repository import HistoricalRepository
from app.history.sync import HistoricalSyncService
from app.models import CanonicalTeam, HistoricalMapRecord, ProviderTeamMapping
from app.providers.common import TimedPayload
from app.providers.stratz.history_queries import TEAM_IDENTITY_QUERY
from app.repositories.raw import RawEventRepository


class _Provider:
    normalizer_version = "fixture-v1"

    def __init__(self, name: str) -> None:
        self.name = name
        self.team_ids: list[str] = []

    async def get_team_pro_maps(self, team_id: str, **_kwargs) -> TimedPayload:
        self.team_ids.append(team_id)
        return TimedPayload(
            payload={"matches": []},
            request_started_at=datetime(2026, 1, 1, tzinfo=UTC),
            received_at=datetime(2026, 1, 1, tzinfo=UTC),
        )

    async def get_match_advanced(self, _match_id: int) -> TimedPayload:
        raise AssertionError("empty team history should not fetch match details")


@pytest.mark.asyncio
async def test_stratz_never_receives_opendota_team_id() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    primary = _Provider("stratz")
    fallback = _Provider("opendota")

    async with factory() as session, session.begin():
        canonical_team = CanonicalTeam(id=uuid4(), name="Team A")
        session.add(canonical_team)
        await session.flush()
        session.add(
            ProviderTeamMapping(
                provider="opendota",
                provider_team_id="4242",
                canonical_team_id=canonical_team.id,
            )
        )
        service = HistoricalSyncService(
            primary=primary,
            fallback=fallback,
            raw_events=RawEventRepository(),
            repository=HistoricalRepository(),
        )
        result = await service.sync_team(
            session,
            canonical_team_id=canonical_team.id,
            before=datetime(2026, 1, 2, tzinfo=UTC),
            limit=10,
        )

    assert primary.team_ids == []
    assert fallback.team_ids == ["4242"]
    assert "HISTORICAL_PRIMARY_TEAM_IDENTITY_MISSING" in result.warnings
    await engine.dispose()


@pytest.mark.asyncio
async def test_stratz_identity_query_creates_only_exact_name_mapping() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    class IdentityProvider:
        name = "stratz"
        normalizer_version = "stratz-v2"

        async def get_team_identities(self, team_ids: list[int]) -> TimedPayload:
            assert team_ids == [123]
            return TimedPayload(
                payload={"data": {"teams": [{"id": 123, "name": "Xtreme Gaming"}]}},
                request_started_at=datetime(2026, 1, 1, tzinfo=UTC),
                received_at=datetime(2026, 1, 1, tzinfo=UTC),
            )

    async with factory() as session, session.begin():
        team = CanonicalTeam(name="Xtreme Gaming")
        session.add(team)
        await session.flush()
        session.add(
            ProviderTeamMapping(
                provider="opendota",
                provider_team_id="123",
                canonical_team_id=team.id,
                observed_name="Xtreme Gaming",
            )
        )
        resolver = HistoricalTeamResolver(RawEventRepository())
        resolved = await resolver.refresh_stratz_identities(
            session,
            IdentityProvider(),
            canonical_team_ids=[team.id],
        )
        mapping = await session.scalar(
            select(ProviderTeamMapping).where(
                ProviderTeamMapping.provider == "stratz",
                ProviderTeamMapping.canonical_team_id == team.id,
            )
        )

    assert TEAM_IDENTITY_QUERY
    assert resolved == 1
    assert mapping is not None and mapping.provider_team_id == "123"
    await engine.dispose()


@pytest.mark.asyncio
async def test_historical_sync_skips_existing_match_ids_before_batching() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    fallback = _Provider("opendota")
    fallback.get_team_pro_maps = lambda *_args, **_kwargs: _timed_payload(
        {"matches": [{"match_id": 1}, {"match_id": 2}]}
    )
    fetched: list[int] = []

    async def fetch_match(match_id: int) -> TimedPayload:
        fetched.append(match_id)
        raise AssertionError("normalization is outside this batching contract test")

    fallback.get_match_advanced = fetch_match
    async with factory() as session, session.begin():
        team = CanonicalTeam(name="Team A")
        session.add(team)
        await session.flush()
        session.add(
            ProviderTeamMapping(
                provider="opendota",
                provider_team_id="10",
                canonical_team_id=team.id,
            )
        )
        session.add(
            HistoricalMapRecord(
                provider="opendota",
                provider_match_id="1",
                started_at=datetime(2025, 1, 1, tzinfo=UTC),
                first_usable_at=datetime(2025, 1, 2, tzinfo=UTC),
                sync_status="BASIC_READY",
                raw_event_id=uuid4(),
            )
        )
        service = HistoricalSyncService(
            primary=None,
            fallback=fallback,
            raw_events=RawEventRepository(),
            repository=HistoricalRepository(),
            batch_size=1,
        )
        with pytest.raises(RuntimeError, match="historical providers failed for match 2"):
            await service.sync_team(
                session,
                canonical_team_id=team.id,
                before=datetime(2026, 1, 1, tzinfo=UTC),
                limit=100,
            )

    assert fetched == [2]
    await engine.dispose()


@pytest.mark.asyncio
async def test_historical_sync_does_not_treat_fallback_fact_as_primary_coverage() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    primary = _Provider("stratz")
    primary.get_team_pro_maps = lambda *_args, **_kwargs: _timed_payload(
        {"data": {"team": {"matches": [{"id": 1, "startDateTime": 1_735_689_600}]}}}
    )
    fetched: list[int] = []

    async def fetch_match(match_id: int) -> TimedPayload:
        fetched.append(match_id)
        raise AssertionError("normalization is outside this provider coverage test")

    primary.get_match_advanced = fetch_match
    fallback = _Provider("opendota")
    async with factory() as session, session.begin():
        team = CanonicalTeam(name="Team A")
        session.add(team)
        await session.flush()
        session.add_all(
            [
                ProviderTeamMapping(
                    provider="stratz",
                    provider_team_id="10",
                    canonical_team_id=team.id,
                ),
                HistoricalMapRecord(
                    provider="opendota",
                    provider_match_id="1",
                    started_at=datetime(2025, 1, 1, tzinfo=UTC),
                    first_usable_at=datetime(2025, 1, 2, tzinfo=UTC),
                    sync_status="BASIC_READY",
                    raw_event_id=uuid4(),
                ),
            ]
        )
        service = HistoricalSyncService(
            primary=primary,
            fallback=fallback,
            raw_events=RawEventRepository(),
            repository=HistoricalRepository(),
            batch_size=1,
        )
        with pytest.raises(RuntimeError, match="historical providers failed for match 1"):
            await service.sync_team(
                session,
                canonical_team_id=team.id,
                before=datetime(2026, 1, 1, tzinfo=UTC),
                limit=100,
            )

    assert fetched == [1]
    await engine.dispose()


async def _timed_payload(payload: dict) -> TimedPayload:
    return TimedPayload(
        payload=payload,
        request_started_at=datetime(2026, 1, 1, tzinfo=UTC),
        received_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
