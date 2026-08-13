from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import Base
from app.domain.history import HistoricalMap, HistoricalMatchBundle
from app.history.identity import HistoricalTeamResolver
from app.jobs.handlers import ApplicationJobHandlers
from app.models import CanonicalTeam, ProviderRawEvent, ProviderTeamMapping
from app.providers.common import TimedPayload
from app.repositories.raw import RawEventRepository


class _Provider:
    def __init__(self, name: str, bundle: HistoricalMatchBundle) -> None:
        self.name = name
        self.normalizer_version = f"{name}-test"
        self._bundle = bundle
        self.calls = 0

    async def get_match_advanced(self, _match_id: int) -> TimedPayload:
        self.calls += 1
        now = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)
        return TimedPayload(
            payload={"provider": self.name},
            request_started_at=now,
            received_at=now,
        )

    def normalize_match(self, _payload: dict, *, fetched_at: datetime):
        return self._bundle.model_copy(
            update={
                "match": self._bundle.match.model_copy(
                    update={"first_usable_at": fetched_at, "fetched_at": fetched_at}
                )
            }
        )


class _TeamResolver:
    async def resolve_observed_match_teams(self, *_args, **_kwargs) -> int:
        return 0


def _bundle(provider: str, *, winner_team_id: str | None) -> HistoricalMatchBundle:
    now = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)
    return HistoricalMatchBundle(
        match=HistoricalMap(
            provider_match_id="8940000001",
            started_at=now,
            radiant_team_id="100",
            dire_team_id="200",
            winner_team_id=winner_team_id,
            provider=provider,
            first_usable_at=now,
            fetched_at=now,
        ),
        players=(),
        advanced_available=False,
    )


@pytest.mark.asyncio
async def test_postmatch_falls_back_when_primary_has_no_result_and_archives_both() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    team_a_id = uuid4()
    team_b_id = uuid4()
    async with factory() as session, session.begin():
        session.add_all(
            (
                CanonicalTeam(id=team_a_id, name="Radiant"),
                CanonicalTeam(id=team_b_id, name="Dire"),
                ProviderTeamMapping(
                    provider="opendota",
                    provider_team_id="100",
                    canonical_team_id=team_a_id,
                ),
                ProviderTeamMapping(
                    provider="opendota",
                    provider_team_id="200",
                    canonical_team_id=team_b_id,
                ),
            )
        )

    primary = _Provider("stratz", _bundle("stratz", winner_team_id=None))
    fallback = _Provider("opendota", _bundle("opendota", winner_team_id="100"))
    handlers = ApplicationJobHandlers(
        SimpleNamespace(
            historical_primary=primary,
            opendota=fallback,
            session_factory=factory,
            raw_events=RawEventRepository(),
            historical_team_resolver=_TeamResolver(),
        )
    )

    provider, _response, bundle, _raw_event_id = await handlers._postmatch_response(
        8940000001,
        expected_team_ids={team_a_id, team_b_id},
    )

    assert provider is fallback
    assert bundle.match.winner_team_id == "100"
    assert primary.calls == 1
    assert fallback.calls == 1
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(ProviderRawEvent)) == 2

    await engine.dispose()


@pytest.mark.asyncio
async def test_postmatch_stays_retryable_when_no_provider_has_a_winner() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    primary = _Provider("stratz", _bundle("stratz", winner_team_id=None))
    fallback = _Provider("opendota", _bundle("opendota", winner_team_id=None))
    handlers = ApplicationJobHandlers(
        SimpleNamespace(
            historical_primary=primary,
            opendota=fallback,
            session_factory=factory,
            raw_events=RawEventRepository(),
            historical_team_resolver=_TeamResolver(),
        )
    )

    with pytest.raises(RuntimeError, match="postmatch result unavailable"):
        await handlers._postmatch_response(8940000001, expected_team_ids=set())

    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(ProviderRawEvent)) == 2

    await engine.dispose()


@pytest.mark.asyncio
async def test_observed_postmatch_team_ids_resolve_only_by_expected_aliases() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    team_a_id = uuid4()
    team_b_id = uuid4()
    async with factory() as session, session.begin():
        session.add_all(
            (
                CanonicalTeam(id=team_a_id, name="Team Falcons"),
                CanonicalTeam(id=team_b_id, name="LGD Gaming"),
            )
        )
    async with factory() as session, session.begin():
        resolved = await HistoricalTeamResolver(
            RawEventRepository()
        ).resolve_observed_match_teams(
            session,
            provider="opendota",
            observed_teams=(("9247354", "Team Falcons"), ("10150538", "LGD Gaming")),
            expected_team_ids={team_a_id, team_b_id},
        )
        assert resolved == 2
    async with factory() as session:
        mappings = list(
            (
                await session.scalars(
                    select(ProviderTeamMapping).where(
                        ProviderTeamMapping.provider == "opendota"
                    )
                )
            ).all()
        )
        assert {item.provider_team_id for item in mappings} == {"9247354", "10150538"}
        assert {item.canonical_team_id for item in mappings} == {team_a_id, team_b_id}

    await engine.dispose()
