import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import Base
from app.events.outbox import EventRepository
from app.market.collector import RayBetOddsCollector
from app.market.odds_registry import OddsRegistry
from app.models import DomainEventRecord, OddsObservationRecord, ProviderRawEvent
from app.providers.raybet.parser import (
    parse_matches,
    parse_odds_bootstrap,
    parse_odds_registry,
    parse_socket_publish,
)
from app.providers.raybet.socket import RayBetSocketClient
from app.repositories.raw import RawEventRepository

FIXTURES = Path(__file__).parent / "fixtures"


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_recorded_match_and_odds_payloads_preserve_provider_contract() -> None:
    observed_at = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)
    matches = parse_matches(
        _fixture("raybet_match.json"),
        observed_at=observed_at,
        dota_game_id=151,
        naive_timezone="Asia/Shanghai",
    )
    metadata = parse_odds_registry(_fixture("raybet_odds.json"))
    bootstrap = parse_odds_bootstrap(_fixture("raybet_odds.json"))
    socket = parse_socket_publish(_fixture("raybet_socket_odds.json"))

    assert len(matches) == 1
    assert matches[0].team_a_name == "Radiant Sample"
    assert matches[0].scheduled_at == datetime(2026, 8, 12, 12, 30, tzinfo=UTC)
    assert [item.odds_id for item in metadata] == [75240285, 75240286]
    assert [item.raw_status for item in metadata] == [4, 5]
    assert [item.raw_status for item in bootstrap] == [4, 5]
    assert socket[0].raw_status == 1
    assert socket[0].provider_updated_at == datetime.fromtimestamp(1786467681, tz=UTC)


@pytest.mark.asyncio
async def test_unknown_socket_odds_is_archived_and_requests_registry_refresh() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    collector = RayBetOddsCollector(
        raw_events=RawEventRepository(),
        registry=OddsRegistry(),
        events=EventRepository(),
        significant_move=0.05,
    )
    received_at = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)

    async with factory() as session, session.begin():
        appended = await collector.collect(
            session,
            _fixture("raybet_socket_odds.json"),
            received_at=received_at,
        )
    assert appended == 0

    async with factory() as session:
        raw_count = await session.scalar(select(func.count()).select_from(ProviderRawEvent))
        odds_count = await session.scalar(select(func.count()).select_from(OddsObservationRecord))
        event = await session.scalar(select(DomainEventRecord))
        assert raw_count == 1
        assert odds_count == 0
        assert event is not None
        assert event.event_type == "ODDS_REGISTRY_REFRESH_REQUIRED"
        assert event.payload["odds_id"] == 75240285
    await engine.dispose()


class _FakeRayBetConnection:
    def __init__(self, publish: dict) -> None:
        self._responses = iter(("{" + '"rid":1}', "{" + '"rid":2}'))
        self._publish = json.dumps(publish)
        self.sent: list[str] = []

    async def send(self, value: str) -> None:
        self.sent.append(value)

    async def recv(self) -> str:
        return next(self._responses)

    def __aiter__(self):
        self._used = False
        return self

    async def __anext__(self) -> str:
        if self._used:
            raise StopAsyncIteration
        self._used = True
        return self._publish


class _FakeConnectContext:
    def __init__(self, connection: _FakeRayBetConnection, *, fail: bool) -> None:
        self._connection = connection
        self._fail = fail

    async def __aenter__(self):
        if self._fail:
            raise ConnectionError("recorded disconnect")
        return self._connection

    async def __aexit__(self, *_args) -> None:
        return None


@pytest.mark.asyncio
async def test_raybet_socket_reconnects_and_resubscribes(monkeypatch) -> None:
    from app.providers.raybet import socket as socket_module

    connection = _FakeRayBetConnection(_fixture("raybet_socket_odds.json"))
    attempts = 0

    def fake_connect(*_args, **_kwargs):
        nonlocal attempts
        attempts += 1
        return _FakeConnectContext(connection, fail=attempts == 1)

    monkeypatch.setattr(socket_module, "connect", fake_connect)
    client = RayBetSocketClient("wss://recorded.invalid", "https://recorded.invalid")
    states: list[str] = []

    async def on_publish(_message: dict) -> None:
        await client.stop()

    async def on_state(state: str, _error: str | None) -> None:
        states.append(state)

    await client.run(on_publish, on_state)

    assert attempts == 2
    assert states == ["CONNECTING", "DISCONNECTED", "CONNECTING", "CONNECTED"]
    assert any('"#subscribe"' in item for item in connection.sent)
    assert any('"channel":"match"' in item for item in connection.sent)
