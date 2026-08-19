import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import Base
from app.events.outbox import EventRepository
from app.live.collector import DltvSocketCollector
from app.models import (
    CanonicalMap,
    CanonicalSeries,
    CanonicalTeam,
    DltvLiveObservationRecord,
    DomainEventRecord,
    ProviderRawEvent,
)
from app.providers.dltv.parser import (
    delayed_detail_is_fresh,
    parse_bootstrap_identity,
    parse_draft,
    parse_draft_labels,
    parse_fast_patch,
)
from app.providers.dltv.reducer import reduce_fast_state
from app.providers.dltv.socket import DltvSocketClient
from app.repositories.raw import RawEventRepository
from app.runtime.health import HealthRegistry
from app.runtime.supervisor import Supervisor
from app.runtime.worker import ServiceWorker

FIXTURES = Path(__file__).parent / "fixtures"


def _fixture() -> dict:
    return json.loads((FIXTURES / "dltv_bootstrap.json").read_text(encoding="utf-8"))


def test_recorded_bootstrap_resolves_identity_and_ten_draft_slots() -> None:
    payload = _fixture()
    identity = parse_bootstrap_identity(payload, valve_match_id=8940730389)
    draft = parse_draft(payload)

    assert identity.series_id == 427609
    assert identity.map_number == 2
    assert draft.complete is True
    assert len(draft.slots) == 10
    for side in ("radiant", "dire"):
        assert {slot.position for slot in draft.slots if slot.side == side} == set(range(1, 6))


def test_prepick_bootstrap_preserves_player_slots_with_unknown_heroes() -> None:
    payload = _fixture()
    for player in payload["players"]:
        player["hero_id"] = 0

    draft = parse_draft(payload)

    assert draft.complete is False
    assert len(draft.slots) == 10
    assert all(slot.account_id is not None for slot in draft.slots)
    assert all(slot.hero_id is None for slot in draft.slots)
    assert draft.blockers == ("DRAFT_PARTIAL",)
    for side in ("radiant", "dire"):
        assert {slot.position for slot in draft.slots if slot.side == side} == set(range(1, 6))


def test_draft_labels_use_structured_identity_fields_not_live_metrics() -> None:
    payload = _fixture()
    payload["live_league_data"] = {
        "stream_delay_s": 900,
        "players": [{"account_id": 1001, "name": "Player One", "hero_id": 1}],
    }
    payload["full_stats"] = {
        "radiant": {
            "players": [
                {
                    "player": {"steam_id": 1001, "title": "Player One Updated"},
                    "hero": {"steam_id": 1, "title": "Anti-Mage"},
                    "net_worth": 99999,
                }
            ]
        }
    }

    player_names, hero_names = parse_draft_labels(payload)

    assert player_names == {1001: "Player One Updated"}
    assert hero_names == {1: "Anti-Mage"}


def test_fast_state_sparse_merge_and_duplicate_timestamps() -> None:
    payload = _fixture()
    received_at = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)
    first = reduce_fast_state(
        None,
        parse_fast_patch(payload, valve_match_id=8940730389, received_at=received_at),
    )
    assert first.state is not None
    duplicate_at = datetime(2026, 8, 12, 12, 0, 5, tzinfo=UTC)
    duplicate = reduce_fast_state(
        first.state,
        parse_fast_patch(payload, valve_match_id=8940730389, received_at=duplicate_at),
    )
    sparse = reduce_fast_state(
        first.state,
        parse_fast_patch(
            {"game_time": 1062},
            valve_match_id=8940730389,
            received_at=duplicate_at,
        ),
    )

    assert first.state.game_time_seconds == 1061
    assert first.state.radiant_nw_lead == -6643
    assert duplicate.changed is False
    assert duplicate.state is not None
    assert duplicate.state.last_message_received_at == duplicate_at
    assert duplicate.state.last_state_change_received_at == received_at
    assert sparse.state is not None
    assert sparse.state.radiant_kills == first.state.radiant_kills
    assert sparse.state.radiant_nw_lead == -6643
    assert delayed_detail_is_fresh(payload, max_delay_seconds=30) is False


def test_fast_state_explicit_null_and_game_time_regression() -> None:
    started_at = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)
    initial = reduce_fast_state(
        None,
        parse_fast_patch(
            {"game_time": 100, "radiant_score": 5, "first_blood": "radiant"},
            valve_match_id=1,
            received_at=started_at,
        ),
    )
    assert initial.state is not None
    reduced = reduce_fast_state(
        initial.state,
        parse_fast_patch(
            {"game_time": 99, "first_blood": None},
            valve_match_id=1,
            received_at=datetime(2026, 8, 12, 12, 0, 5, tzinfo=UTC),
        ),
    )

    assert reduced.state is not None
    assert reduced.state.game_time_seconds == 100
    assert reduced.state.first_blood is None
    assert "DLTV_GAME_TIME_REGRESSION" in reduced.warnings


@pytest.mark.asyncio
async def test_duplicate_socket_state_keeps_raw_but_not_normalized_duplicate() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    valve_match_id = 8940730389
    async with factory() as session, session.begin():
        team_a = CanonicalTeam(name="A")
        team_b = CanonicalTeam(name="B")
        session.add_all((team_a, team_b))
        await session.flush()
        series = CanonicalSeries(team_a_id=team_a.id, team_b_id=team_b.id)
        session.add(series)
        await session.flush()
        session.add(CanonicalMap(series_id=series.id, valve_match_id=valve_match_id))

    collector = DltvSocketCollector(
        session_factory=factory,
        raw_events=RawEventRepository(),
        events=EventRepository(),
    )
    payload = {
        "game_time": 1061,
        "radiant_score": 10,
        "dire_score": 10,
        "radiant_lead": -6643,
    }
    event_name = f"__nd2_match_{valve_match_id}"
    first_at = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)
    second_at = datetime(2026, 8, 12, 12, 0, 7, tzinfo=UTC)
    await collector.collect(event_name, payload, "connection-a", 1, received_at=first_at)
    await collector.collect(event_name, payload, "connection-b", 2, received_at=second_at)

    async with factory() as session:
        raw = list(
            (
                await session.scalars(
                    select(ProviderRawEvent).order_by(ProviderRawEvent.received_at)
                )
            ).all()
        )
        normalized = list(
            (
                await session.scalars(
                    select(DltvLiveObservationRecord).order_by(
                        DltvLiveObservationRecord.received_at
                    )
                )
            ).all()
        )
        normalized_count = len(normalized)

    assert len(raw) == 2
    assert normalized_count == 1
    assert raw[0].is_duplicate is False
    assert raw[1].is_duplicate is True
    assert raw[0].normalized_state_hash == raw[1].normalized_state_hash
    assert raw[1].connection_id == "connection-b"
    assert raw[1].reconnect_generation == 2
    # The duplicate packet refreshes message freshness without creating a new
    # state row: live phase stays LIVE while state-change age remains frozen.
    assert normalized[0].received_at == first_at.replace(tzinfo=None)
    assert normalized[0].last_message_received_at == second_at.replace(tzinfo=None)
    assert normalized[0].last_state_change_received_at == first_at.replace(tzinfo=None)
    assert normalized[0].game_time_seconds == 1061
    await engine.dispose()


@pytest.mark.asyncio
async def test_series_frame_removal_emits_one_map_ended_event() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    valve_match_id = 8940730389
    async with factory() as session, session.begin():
        team_a = CanonicalTeam(name="A")
        team_b = CanonicalTeam(name="B")
        session.add_all((team_a, team_b))
        await session.flush()
        series = CanonicalSeries(team_a_id=team_a.id, team_b_id=team_b.id)
        session.add(series)
        await session.flush()
        canonical_map = CanonicalMap(series_id=series.id, valve_match_id=valve_match_id)
        session.add(canonical_map)
        await session.flush()
        canonical_map_id = canonical_map.id

    collector = DltvSocketCollector(
        session_factory=factory,
        raw_events=RawEventRepository(),
        events=EventRepository(),
    )
    live_at = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)
    ended_at = datetime(2026, 8, 12, 12, 45, tzinfo=UTC)
    await collector.collect(
        "__nd2_series",
        {"live": {str(valve_match_id): 427609}},
        received_at=live_at,
    )
    await collector.collect("__nd2_series", {"live": {}}, received_at=ended_at)
    await collector.collect("__nd2_series", {"live": {}}, received_at=ended_at)

    async with factory() as session:
        ended_events = list(
            (
                await session.scalars(
                    select(DomainEventRecord).where(DomainEventRecord.event_type == "MAP_ENDED")
                )
            ).all()
        )

    assert len(ended_events) == 1
    assert ended_events[0].aggregate_id == str(canonical_map_id)
    assert ended_events[0].payload == {
        "canonical_map_id": str(canonical_map_id),
        "valve_match_id": valve_match_id,
    }
    assert ended_events[0].occurred_at == ended_at.replace(tzinfo=None)
    await engine.dispose()


@pytest.mark.asyncio
async def test_series_frame_removal_requeues_identity_with_end_evidence() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    valve_match_id = 8940730389
    series_id = 427609
    collector = DltvSocketCollector(
        session_factory=factory,
        raw_events=RawEventRepository(),
        events=EventRepository(),
    )
    live_at = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)
    ended_at = datetime(2026, 8, 12, 12, 45, tzinfo=UTC)

    await collector.collect(
        "__nd2_series",
        {"live": {str(valve_match_id): series_id}},
        received_at=live_at,
    )
    await collector.collect("__nd2_series", {"live": {}}, received_at=ended_at)

    async with factory() as session:
        events = list(
            (
                await session.scalars(
                    select(DomainEventRecord)
                    .where(DomainEventRecord.event_type == "DLTV_MATCH_DISCOVERED")
                    .order_by(DomainEventRecord.occurred_at)
                )
            ).all()
        )

    assert len(events) == 2
    assert events[1].dedupe_key == f"dltv-ended:{valve_match_id}"
    assert events[1].payload == {
        "valve_match_id": valve_match_id,
        "dltv_series_id": series_id,
        "ended_at": ended_at.isoformat(),
        "reason": "MAP_ENDED_IDENTITY_PENDING",
    }
    await engine.dispose()


class _FakeSocketIo:
    def __init__(self) -> None:
        self.connected = False
        self.connect_attempts = 0
        self.handlers: dict[str, object] = {}
        self._wait = asyncio.Event()

    def event(self, function):
        self.handlers[function.__name__] = function
        return function

    def on(self, event_name: str):
        def register(function):
            self.handlers[event_name] = function
            return function

        return register

    async def connect(self, *_args, **_kwargs) -> None:
        self.connect_attempts += 1
        if self.connect_attempts == 1:
            raise ConnectionError("recorded 502")
        self.connected = True
        await self.handlers["connect"]()

    async def wait(self) -> None:
        await self._wait.wait()

    async def disconnect(self) -> None:
        self.connected = False
        self._wait.set()


@pytest.mark.asyncio
async def test_dltv_socket_is_restarted_after_connect_failure() -> None:
    client = DltvSocketClient("https://recorded.invalid")
    fake_socket = _FakeSocketIo()
    client._sio = fake_socket
    health = HealthRegistry()
    connected = asyncio.Event()

    async def on_event(
        _event: str,
        _payload: dict,
        _connection_id: str,
        _reconnect_generation: int,
    ) -> None:
        return None

    async def on_state(state: str, _error: str | None) -> None:
        if state == "CONNECTED":
            connected.set()

    worker = ServiceWorker(
        name="DltvSocketWorker",
        run=lambda: client.run(on_event, on_state),
        stop=client.stop,
        health_registry=health,
    )
    supervisor = Supervisor([worker], health=health, max_backoff_seconds=0.01)
    task = asyncio.create_task(supervisor.run())
    await asyncio.wait_for(connected.wait(), timeout=1)
    await supervisor.stop()
    await task

    snapshot = await health.worker("DltvSocketWorker")
    assert fake_socket.connect_attempts >= 2
    assert snapshot["restart_count"] >= 1
