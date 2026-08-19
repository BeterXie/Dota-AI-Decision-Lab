import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import Base
from app.domain.history import HistoricalMap, HistoricalMatchBundle
from app.domain.jobs import DurableJob, JobStatus, JobType
from app.evaluation.settlement import SettlementService
from app.events.outbox import EventRepository
from app.history.identity import HistoricalTeamResolver
from app.history.repository import HistoricalRepository
from app.jobs.handlers import ApplicationJobHandlers
from app.models import (
    CanonicalMap,
    CanonicalSeries,
    CanonicalTeam,
    HistoricalMapRecord,
    MapResultEvidenceRecord,
    MapResultRecord,
    ProviderRawEvent,
    ProviderTeamMapping,
)
from app.providers.common import TimedPayload
from app.providers.dltv.results import DltvResultProvider, normalize_match_result
from app.repositories.raw import RawEventRepository

FIXTURES = Path(__file__).parent / "fixtures"


class _DltvClient:
    def __init__(self, payload: dict) -> None:
        self._payload = payload
        self.calls = 0

    async def get_live(self, match_id: int) -> TimedPayload:
        self.calls += 1
        now = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)
        return TimedPayload(
            payload=self._payload,
            request_started_at=now,
            received_at=now,
        )


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
    async def repair_match_placeholders(self, *_args, **_kwargs) -> int:
        return 0

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
async def test_postmatch_rejects_mismatched_provider_match_identity_and_falls_back() -> None:
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

    mismatched_bundle = _bundle("stratz", winner_team_id="100")
    mismatched_bundle = mismatched_bundle.model_copy(
        update={
            "match": mismatched_bundle.match.model_copy(update={"provider_match_id": "8940000999"})
        }
    )
    primary = _Provider("stratz", mismatched_bundle)
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

    provider, _response, _bundle_result, _raw_event_id = await handlers._postmatch_response(
        8940000001,
        expected_team_ids={team_a_id, team_b_id},
    )

    assert provider is fallback
    assert primary.calls == 1
    assert fallback.calls == 1
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
        placeholder = CanonicalTeam(name="OPENDOTA team 9247354")
        session.add_all(
            (
                CanonicalTeam(id=team_a_id, name="Team Falcons"),
                CanonicalTeam(id=team_b_id, name="LGD Gaming"),
                placeholder,
            )
        )
        await session.flush()
        session.add(
            ProviderTeamMapping(
                provider="opendota",
                provider_team_id="9247354",
                canonical_team_id=placeholder.id,
            )
        )
        placeholder_id = placeholder.id
    async with factory() as session, session.begin():
        resolved = await HistoricalTeamResolver(RawEventRepository()).resolve_observed_match_teams(
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
                    select(ProviderTeamMapping).where(ProviderTeamMapping.provider == "opendota")
                )
            ).all()
        )
        assert {item.provider_team_id for item in mappings} == {"9247354", "10150538"}
        assert {item.canonical_team_id for item in mappings} == {team_a_id, team_b_id}
        assert await session.get(CanonicalTeam, placeholder_id) is None

    await engine.dispose()


@pytest.mark.asyncio
async def test_match_context_merges_placeholder_and_restores_converged_result() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)
    async with factory() as session, session.begin():
        team_a = CanonicalTeam(name="Team Falcons")
        team_b = CanonicalTeam(name="Vici Gaming")
        placeholder = CanonicalTeam(name="STRATZ team 9247354")
        session.add_all((team_a, team_b, placeholder))
        await session.flush()
        series = CanonicalSeries(team_a_id=team_a.id, team_b_id=team_b.id)
        session.add(series)
        await session.flush()
        canonical_map = CanonicalMap(
            series_id=series.id,
            map_number=2,
            valve_match_id=8948040486,
        )
        session.add(canonical_map)
        await session.flush()
        session.add_all(
            (
                ProviderTeamMapping(
                    provider="stratz",
                    provider_team_id="9247354",
                    canonical_team_id=placeholder.id,
                ),
                HistoricalMapRecord(
                    canonical_map_id=canonical_map.id,
                    provider="stratz",
                    provider_match_id="8948040486",
                    started_at=now,
                    radiant_team_id=placeholder.id,
                    dire_team_id=team_b.id,
                    winner_team_id=placeholder.id,
                    first_usable_at=now,
                    sync_status="DATA_CONFLICT",
                    raw_event_id=uuid4(),
                ),
                HistoricalMapRecord(
                    canonical_map_id=canonical_map.id,
                    provider="opendota",
                    provider_match_id="8948040486",
                    started_at=now,
                    radiant_team_id=team_a.id,
                    dire_team_id=team_b.id,
                    winner_team_id=team_a.id,
                    first_usable_at=now,
                    sync_status="DATA_CONFLICT",
                    raw_event_id=uuid4(),
                ),
                MapResultEvidenceRecord(
                    canonical_map_id=canonical_map.id,
                    provider="opendota",
                    provider_match_id="8948040486",
                    winner_team_id=team_a.id,
                    result_observed_at=now,
                    first_usable_at=now,
                    raw_event_id=uuid4(),
                    normalizer_version="fixture-v1",
                    identity_confidence=1.0,
                    conflict_status="DATA_CONFLICT",
                ),
                MapResultRecord(
                    canonical_map_id=canonical_map.id,
                    winner_team_id=None,
                    basic_first_usable_at=now,
                    provider_conflict=True,
                ),
            )
        )
        placeholder_id = placeholder.id
        team_a_id = team_a.id
        team_b_id = team_b.id
        canonical_map_id = canonical_map.id

    async with factory() as session, session.begin():
        resolved = await HistoricalTeamResolver(RawEventRepository()).repair_match_placeholders(
            session,
            provider_match_id="8948040486",
            expected_team_ids={team_a_id, team_b_id},
        )
        assert resolved == 1

    async with factory() as session:
        mapping = await session.scalar(
            select(ProviderTeamMapping).where(
                ProviderTeamMapping.provider == "stratz",
                ProviderTeamMapping.provider_team_id == "9247354",
            )
        )
        facts = list(
            (
                await session.scalars(
                    select(HistoricalMapRecord).where(
                        HistoricalMapRecord.canonical_map_id == canonical_map_id
                    )
                )
            ).all()
        )
        evidence = await session.scalar(
            select(MapResultEvidenceRecord).where(
                MapResultEvidenceRecord.canonical_map_id == canonical_map_id
            )
        )
        result = await session.scalar(
            select(MapResultRecord).where(MapResultRecord.canonical_map_id == canonical_map_id)
        )
        placeholder_record = await session.get(CanonicalTeam, placeholder_id)

    assert mapping is not None and mapping.canonical_team_id == team_a_id
    assert placeholder_record is None
    assert {fact.winner_team_id for fact in facts} == {team_a_id}
    assert {fact.sync_status for fact in facts} == {"BASIC_READY"}
    assert evidence is not None and evidence.conflict_status == "CONFIRMED"
    assert result is not None and result.winner_team_id == team_a_id
    assert result.provider_conflict is False
    await engine.dispose()


def test_dltv_result_normalizer_maps_winner_through_explicit_side_flags() -> None:
    payload = json.loads((FIXTURES / "dltv_result.json").read_text(encoding="utf-8"))
    fetched_at = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)

    bundle = normalize_match_result(payload, fetched_at=fetched_at)

    # Recorded DLTV provider ordering is reversed: first_team is Dire.
    assert bundle.match.provider == "dltv"
    assert bundle.match.provider_match_id == "8940730389"
    assert bundle.match.radiant_team_id == "8006"
    assert bundle.match.dire_team_id == "6014"
    assert bundle.match.winner_team_id == "6014"
    assert bundle.match.first_usable_at == fetched_at
    assert bundle.advanced_available is False
    assert bundle.players == ()


def test_dltv_result_normalizer_keeps_unpublished_winner_unknown() -> None:
    payload = json.loads((FIXTURES / "dltv_result.json").read_text(encoding="utf-8"))
    payload.pop("winner")

    with pytest.raises(ValueError, match="winner is not published"):
        normalize_match_result(payload, fetched_at=datetime(2026, 8, 12, 12, 0, tzinfo=UTC))


def test_dltv_result_normalizer_requires_explicit_radiant_dire_evidence() -> None:
    payload = json.loads((FIXTURES / "dltv_result.json").read_text(encoding="utf-8"))
    payload["db"]["first_team"].pop("is_radiant")

    with pytest.raises(ValueError, match="side identity is incomplete"):
        normalize_match_result(payload, fetched_at=datetime(2026, 8, 12, 12, 0, tzinfo=UTC))


@pytest.mark.asyncio
async def test_postmatch_falls_back_to_dltv_when_other_providers_have_no_winner() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    team_a_id = uuid4()
    team_b_id = uuid4()
    payload = json.loads((FIXTURES / "dltv_result.json").read_text(encoding="utf-8"))
    dltv_client = _DltvClient(payload)
    dltv = DltvResultProvider(dltv_client)
    async with factory() as session, session.begin():
        session.add_all(
            (
                CanonicalTeam(id=team_a_id, name="Level UP"),
                CanonicalTeam(id=team_b_id, name="Spirit Academy"),
                ProviderTeamMapping(
                    provider="dltv",
                    provider_team_id="6014",
                    canonical_team_id=team_a_id,
                ),
                ProviderTeamMapping(
                    provider="dltv",
                    provider_team_id="8006",
                    canonical_team_id=team_b_id,
                ),
            )
        )

    primary = _Provider("stratz", _bundle("stratz", winner_team_id=None))
    fallback = _Provider("opendota", _bundle("opendota", winner_team_id=None))
    handlers = ApplicationJobHandlers(
        SimpleNamespace(
            historical_primary=primary,
            opendota=fallback,
            dltv_result=dltv,
            session_factory=factory,
            raw_events=RawEventRepository(),
            historical_team_resolver=_TeamResolver(),
        )
    )

    provider, _response, bundle, raw_event_id = await handlers._postmatch_response(
        8940730389,
        expected_team_ids={team_a_id, team_b_id},
    )

    assert provider is dltv
    assert bundle.match.winner_team_id == "6014"
    assert primary.calls == 1
    assert fallback.calls == 1
    assert dltv_client.calls == 1
    async with factory() as session:
        raw = await session.scalar(
            select(ProviderRawEvent).where(ProviderRawEvent.id == raw_event_id)
        )
        assert raw is not None
        assert raw.provider == "dltv"
        assert raw.event_type == "DLTV_POSTMATCH"
        assert raw.provider_key == "8940730389"

    await engine.dispose()


@pytest.mark.asyncio
async def test_resolve_postmatch_settles_from_dltv_result_evidence() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    payload = json.loads((FIXTURES / "dltv_result.json").read_text(encoding="utf-8"))
    dltv = DltvResultProvider(_DltvClient(payload))
    handlers = ApplicationJobHandlers(
        SimpleNamespace(
            historical_primary=None,
            opendota=None,
            dltv_result=dltv,
            session_factory=factory,
            raw_events=RawEventRepository(),
            historical_team_resolver=HistoricalTeamResolver(RawEventRepository()),
            historical_repository=HistoricalRepository(),
            settlement=SettlementService(),
            events=EventRepository(),
        )
    )
    async with factory() as session, session.begin():
        team_a = CanonicalTeam(name="Level UP")
        team_b = CanonicalTeam(name="Spirit Academy")
        session.add_all((team_a, team_b))
        await session.flush()
        series = CanonicalSeries(team_a_id=team_a.id, team_b_id=team_b.id)
        session.add(series)
        await session.flush()
        canonical_map = CanonicalMap(
            series_id=series.id,
            valve_match_id=8940730389,
            map_number=2,
        )
        session.add(canonical_map)
        await session.flush()
        session.add_all(
            (
                ProviderTeamMapping(
                    provider="dltv",
                    provider_team_id="6014",
                    canonical_team_id=team_a.id,
                ),
                ProviderTeamMapping(
                    provider="dltv",
                    provider_team_id="8006",
                    canonical_team_id=team_b.id,
                ),
            )
        )
        canonical_map_id = canonical_map.id

    job = DurableJob(
        id=uuid4(),
        job_type=JobType.RESOLVE_POSTMATCH,
        dedupe_key="dltv-postmatch-fixture",
        payload={"canonical_map_id": str(canonical_map_id)},
        status=JobStatus.RUNNING,
        priority=100,
        not_before=datetime(2026, 8, 12, 12, 0, tzinfo=UTC),
        created_at=datetime(2026, 8, 12, 12, 0, tzinfo=UTC),
        attempt_count=1,
        max_attempts=10,
        locked_by="fixture",
        locked_at=datetime(2026, 8, 12, 12, 0, tzinfo=UTC),
    )

    await handlers.resolve_postmatch(job)

    async with factory() as session:
        fact = await session.scalar(
            select(HistoricalMapRecord).where(
                HistoricalMapRecord.provider == "dltv",
                HistoricalMapRecord.provider_match_id == "8940730389",
            )
        )
        result = await session.scalar(
            select(MapResultRecord).where(MapResultRecord.canonical_map_id == canonical_map_id)
        )
        evidence = await session.scalar(
            select(MapResultEvidenceRecord).where(
                MapResultEvidenceRecord.canonical_map_id == canonical_map_id
            )
        )
        assert fact is not None and fact.winner_team_id == team_a.id
        assert result is not None and result.winner_team_id == team_a.id
        assert result.provider_conflict is False
        assert evidence is not None
        assert evidence.provider == "dltv"
        assert evidence.conflict_status == "CONFIRMED"
        assert evidence.normalizer_version == dltv.normalizer_version

    await engine.dispose()
